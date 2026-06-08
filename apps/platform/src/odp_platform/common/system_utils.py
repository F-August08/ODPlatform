#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : system_utils.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : 环境快照——采集运行环境信息(创建用户 / OS / CPU / 内存 / GPU /
#              CUDA / Python / PyTorch / Ultralytics / 核心依赖版本),
#              用于训练复现与线上排障
#
# 设计哲学:
#   - 底层基础设施:仅依赖 Python 标准库 + 同层 string_utils(纯 stdlib)。
#   - 运行环境只保证装了 Python,其余一律"探测式获取":
#       三方库缺失 / 外部命令不存在 / 调用异常,全部不会让本模块崩溃,
#       统一降级为占位值(N/A、未安装),保证每个字段恒在、可序列化、可对齐。
#   - 日志走项目 logger 树:模块顶部 getLogger(__name__),自己不挂 handler;
#     由 CLI 入口的 get_logger() 统一装配后,本模块的日志冒泡过去被处理
#     ——所以本模块【不 import logging_utils】,也就不背 colorlog 依赖。

import os
import sys
import json
import socket
import getpass
import platform
import logging
import importlib
import subprocess
import shutil
import importlib.metadata as importlib_metadata
from datetime import datetime
from typing import Optional, Any, Dict, List

from odp_platform.common.string_utils import (
    pad_to_width,
    format_table_row,
    format_table_separator,
)


# 模块级 logger:业务/工具模块的标准写法,不配 handler,靠冒泡到根 logger
logger = logging.getLogger(__name__)

# 探测失败 / 不可用 / 未安装 时统一使用的占位符
_NA = "N/A"
_NOT_INSTALLED = "未安装"

# "核心依赖库"区块要展示版本的包。每行:
#   (展示名, [候选发行包名...], 轻量 import 名兜底 or None)
#   - 发行包名可能与 import 名不同(cv2→opencv-python、PIL→Pillow、yaml→PyYAML);
#     故用候选列表逐个查 importlib.metadata。
#   - import 名兜底仅对【轻量】包开启(查不到 metadata 时导入读 __version__);
#     torch/ultralytics 置 None 禁用导入兜底——它们重、且各自有专属区块。
_CORE_PACKAGES = [
    ("numpy",        ["numpy"],                                                   "numpy"),
    ("torch",        ["torch"],                                                   None),
    ("torchvision",  ["torchvision"],                                             None),
    ("ultralytics",  ["ultralytics"],                                             None),
    ("opencv (cv2)", ["opencv-python", "opencv-python-headless",
                      "opencv-contrib-python", "opencv-contrib-python-headless"], "cv2"),
    ("Pillow (PIL)", ["Pillow", "pillow"],                                        "PIL"),
    ("PyYAML",       ["PyYAML", "pyyaml"],                                        "yaml"),
    ("matplotlib",   ["matplotlib"],                                              "matplotlib"),
    ("pandas",       ["pandas"],                                                  "pandas"),
    ("tqdm",         ["tqdm"],                                                    "tqdm"),
    # —— 目标检测/评估/导出/可视化常用(没装就显示"未安装",纯信息)——
    ("scipy",        ["scipy"],                                                   "scipy"),
    ("psutil",       ["psutil"],                                                  "psutil"),
    ("seaborn",      ["seaborn"],                                                 "seaborn"),
    ("pycocotools",  ["pycocotools"],                                             "pycocotools"),
    ("onnx",         ["onnx"],                                                    "onnx"),
    ("onnxruntime",  ["onnxruntime", "onnxruntime-gpu"],                          "onnxruntime"),
    ("tensorboard",  ["tensorboard"],                                             "tensorboard"),
]


# ===========================================================================
# 一、安全探测小工具:任何异常都吞掉并返回降级值,确保"只装了 Python"也能跑
# ===========================================================================
def _safe_import(module_name: str):
    """尝试导入模块,失败(未安装 / 导入即报错)返回 None,绝不抛出。"""
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def _pkg_version(dist_name: str) -> Optional[str]:
    """查询【已安装发行包】的版本号,查不到返回 None;不会真正 import 该包。"""
    try:
        return importlib_metadata.version(dist_name)
    except Exception:
        return None


def _resolve_version(dist_candidates: List[str], import_name: Optional[str]) -> str:
    """按候选发行包名依次查版本;都查不到时,对轻量包尝试导入读 __version__。"""
    for dist in dist_candidates:
        version = _pkg_version(dist)
        if version:
            return version
    if import_name:
        mod = _safe_import(import_name)
        if mod is not None:
            return str(getattr(mod, "__version__", "已安装(版本未知)"))
    return _NOT_INSTALLED


def _run_command(cmd: List[str], timeout: float = 5.0) -> Optional[str]:
    """运行外部命令并返回 stdout(已 strip)。命令不存在 / 超时 / 非零退出均返回 None。"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except Exception:
        return None


def _fmt_bytes(num_bytes: Any) -> str:
    """把字节数转成人类可读(B/KiB/MiB/GiB/TiB);非法输入返回 N/A。"""
    try:
        num = float(num_bytes)
    except Exception:
        return _NA
    for unit in ("B", "KiB", "MiB", "GiB"):
        if num < 1024:
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TiB"


# ===========================================================================
# 二、各区块采集器(每个都内部容错,返回 {字段: 值} 字典)
# ===========================================================================
def _get_git_commit() -> str:
    """当前项目 Git 短 commit(+ 是否有未提交改动);非 git 仓库 / 无 git 返回降级值。"""
    commit = _run_command(["git", "rev-parse", "--short", "HEAD"])
    if not commit:
        return f"{_NA} (非 git 仓库 / 无 git)"
    dirty = _run_command(["git", "status", "--porcelain"])
    return f"{commit} (有未提交改动)" if dirty else commit


def _collect_snapshot_meta() -> Dict[str, Any]:
    """快照元信息:谁、在哪台机器、什么时候、在哪个目录、什么代码版本生成的。"""
    try:
        user = getpass.getuser()
    except Exception:
        # 无 home / 无 passwd 数据库的环境 getuser 可能抛错,退回环境变量
        user = os.environ.get("USER") or os.environ.get("USERNAME") or _NA
    try:
        hostname = socket.gethostname() or platform.node() or _NA
    except Exception:
        hostname = _NA
    return {
        "创建用户": user,
        "主机名": hostname,
        "创建时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "工作目录": os.getcwd(),
        "Git 提交": _get_git_commit(),
    }


def _collect_python_info() -> Dict[str, Any]:
    """Python 解释器信息 + 虚拟环境识别(conda / venv)。"""
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    venv = os.environ.get("VIRTUAL_ENV")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if conda_env:
        env_desc = f"conda: {conda_env}"
    elif venv:
        env_desc = f"venv: {os.path.basename(venv)}"
    elif in_venv:
        env_desc = "venv (未命名)"
    else:
        env_desc = "系统全局 (非虚拟环境)"
    return {
        "版本": platform.python_version(),
        "实现": platform.python_implementation(),
        "解释器路径": sys.executable or _NA,
        "虚拟环境": env_desc,
    }


def _collect_os_info() -> Dict[str, Any]:
    """操作系统信息。"""
    return {
        "系统": platform.system() or _NA,
        "发行版本": platform.release() or _NA,
        "完整描述": platform.platform(),
        "架构": platform.machine() or _NA,
    }


def _get_cpu_model() -> str:
    """尽量拿到 CPU 型号名;各平台策略不同,全部失败则退回架构名。"""
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    elif system == "Darwin":
        name = _run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
        if name:
            return name
    elif system == "Windows":
        # platform.processor() 在 Windows 上返回 "Intel64 Family 6 Model 154 ..." 这种
        # 又长又没用的串;真实型号名("13th Gen Intel(R) Core i9-13900H")在注册表里。
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if name:
                return str(name).strip()
        except Exception:
            pass
    proc = platform.processor()
    return proc or platform.machine() or _NA


def _collect_cpu_info() -> Dict[str, Any]:
    """CPU 信息:型号 + 逻辑核心(stdlib);物理核心需 psutil。"""
    info: Dict[str, Any] = {
        "型号": _get_cpu_model(),
        "逻辑核心数": os.cpu_count() or _NA,
    }
    psutil = _safe_import("psutil")
    if psutil is not None:
        try:
            info["物理核心数"] = psutil.cpu_count(logical=False) or _NA
        except Exception:
            info["物理核心数"] = _NA
    else:
        info["物理核心数"] = f"{_NA} (需 psutil)"
    return info


def _read_meminfo_linux_total_kb() -> Optional[int]:
    """无 psutil 时的 Linux 兜底:从 /proc/meminfo 读 MemTotal(单位 kB)。"""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1])  # 形如 "MemTotal: 16331640 kB"
    except Exception:
        return None
    return None


def _collect_memory_info() -> Dict[str, Any]:
    """内存信息:优先 psutil(总/可用/已用/使用率);否则 Linux 至少给总量。"""
    psutil = _safe_import("psutil")
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            return {
                "总内存": _fmt_bytes(vm.total),
                "可用内存": _fmt_bytes(vm.available),
                "已用内存": _fmt_bytes(vm.used),
                "使用率": f"{vm.percent:.1f}%",
            }
        except Exception:
            pass
    if platform.system() == "Linux":
        total_kb = _read_meminfo_linux_total_kb()
        if total_kb is not None:
            return {"总内存": _fmt_bytes(total_kb * 1024), "详细信息": f"{_NA} (需 psutil)"}
    return {"内存信息": f"{_NA} (需 psutil)"}


def _collect_disk_info() -> Dict[str, Any]:
    """工作目录所在分区的磁盘容量(数据集 / 权重通常很占地);失败降级为 N/A。"""
    try:
        usage = shutil.disk_usage(os.getcwd())
        used_pct = (usage.used / usage.total * 100) if usage.total else 0.0
        return {
            "总空间": _fmt_bytes(usage.total),
            "可用空间": _fmt_bytes(usage.free),
            "使用率": f"{used_pct:.1f}%",
        }
    except Exception:
        return {"磁盘信息": _NA}


def _query_nvidia_smi_gpus() -> List[Dict[str, str]]:
    """用 nvidia-smi 探测物理 GPU(不依赖 torch)。无 GPU / 无命令时返回 []。"""
    out = _run_command([
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return []
    gpus: List[Dict[str, str]] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            gpus.append({
                "name": parts[0],
                "memory_total_mib": parts[1],
                "driver_version": parts[2],
            })
    return gpus


def _get_cuda_toolkit_version() -> str:
    """系统 CUDA Toolkit 版本(nvcc --version 解析);没装 / 不在 PATH 返回降级值。"""
    out = _run_command(["nvcc", "--version"])
    if not out:
        return f"{_NOT_INSTALLED} (或不在 PATH)"
    # nvcc 输出含 "Cuda compilation tools, release 12.1, V12.1.105"
    idx = out.find("release ")
    if idx != -1:
        ver = out[idx + len("release "):].split(",")[0].strip()
        if ver:
            return ver
    return _NA


def _collect_gpu_section() -> Dict[str, Any]:
    """硬件层 GPU 信息(nvidia-smi)+ CUDA_VISIBLE_DEVICES + 系统 CUDA Toolkit。"""
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
    section: Dict[str, Any] = {
        "CUDA_VISIBLE_DEVICES": cvd if cvd is not None else "(未设置, 全部可见)",
        "CUDA Toolkit (nvcc)": _get_cuda_toolkit_version(),
    }
    gpus = _query_nvidia_smi_gpus()
    if not gpus:
        section["NVIDIA GPU"] = f"{_NA} (未检测到 / nvidia-smi 不可用)"
        return section
    section["GPU 数量"] = len(gpus)
    # 型号 / 显存 / 驱动 各自成行:单卡直接给值,多卡按 [i] 分行(均短、右对齐、不折行)
    section["GPU 列表"] = [f"[{i}] {g['name']}" for i, g in enumerate(gpus)]
    if len(gpus) == 1:
        section["显存"] = f"{gpus[0]['memory_total_mib']} MiB"
        section["驱动"] = gpus[0]["driver_version"]
    else:
        section["显存"] = [f"[{i}] {g['memory_total_mib']} MiB" for i, g in enumerate(gpus)]
        section["驱动"] = [f"[{i}] {g['driver_version']}" for i, g in enumerate(gpus)]
    return section


def _collect_pytorch_info() -> Dict[str, Any]:
    """PyTorch 视角:版本 + 它能否用 CUDA + CUDA/cuDNN 版本 + 它看到的 GPU。"""
    torch = _safe_import("torch")
    if torch is None:
        return {"是否安装": _NOT_INSTALLED}

    info: Dict[str, Any] = {"是否安装": "是"}
    info["版本"] = getattr(torch, "__version__", None) or _pkg_version("torch") or _NA

    cuda_available = False
    try:
        cuda_available = bool(torch.cuda.is_available())
    except Exception:
        cuda_available = False
    info["CUDA 可用"] = "是" if cuda_available else "否"

    try:
        info["CUDA 版本"] = getattr(torch.version, "cuda", None) or _NA
    except Exception:
        info["CUDA 版本"] = _NA
    try:
        cudnn_ver = torch.backends.cudnn.version()
        info["cuDNN 版本"] = str(cudnn_ver) if cudnn_ver else _NA
    except Exception:
        info["cuDNN 版本"] = _NA

    if cuda_available:
        try:
            count = torch.cuda.device_count()
            info["可见 GPU 数"] = count
            names, caps = [], []
            for i in range(count):
                try:
                    names.append(f"[{i}] {torch.cuda.get_device_name(i)}")
                except Exception:
                    names.append(f"[{i}] {_NA}")
                try:
                    major, minor = torch.cuda.get_device_capability(i)
                    caps.append(f"{major}.{minor}")
                except Exception:
                    caps.append(_NA)
            info["GPU 设备"] = names
            # 算力(compute capability):单卡纯数值,多卡按 [i] 分行
            if count == 1:
                info["设备算力"] = caps[0]
            elif count > 1:
                info["设备算力"] = [f"[{i}] {c}" for i, c in enumerate(caps)]
        except Exception:
            info["可见 GPU 数"] = _NA
    return info


def _collect_ultralytics_info() -> Dict[str, Any]:
    """Ultralytics 是否安装 + 版本(优先 metadata,避免无谓重导入)。"""
    version = _pkg_version("ultralytics")
    if version is None:
        ul = _safe_import("ultralytics")
        if ul is None:
            return {"是否安装": _NOT_INSTALLED}
        version = getattr(ul, "__version__", _NA)
    return {"是否安装": "是", "版本": version}


def _collect_core_packages() -> Dict[str, Any]:
    """核心依赖库版本清单;逐个探测,缺失显示"未安装"。"""
    return {
        display: _resolve_version(dists, import_name)
        for display, dists, import_name in _CORE_PACKAGES
    }


# ===========================================================================
# 三、对外 API:采集 / 渲染 / 落日志 / 转 JSON
# ===========================================================================
def collect_system_info() -> Dict[str, Dict[str, Any]]:
    """采集完整环境快照,返回按区块组织的字典(JSON 可序列化)。

    任何子项探测失败都会降级为占位值(N/A / 未安装),不会抛异常,
    因此在"仅安装了 Python"的最小环境中也能安全运行。

    Returns:
        形如 {"区块名": {"字段": 值, ...}, ...} 的字典,可直接 json.dumps。
    """
    return {
        "快照信息": _collect_snapshot_meta(),
        "Python 解释器": _collect_python_info(),
        "操作系统": _collect_os_info(),
        "CPU": _collect_cpu_info(),
        "内存": _collect_memory_info(),
        "磁盘 (工作目录所在分区)": _collect_disk_info(),
        "GPU (硬件 / nvidia-smi)": _collect_gpu_section(),
        "PyTorch": _collect_pytorch_info(),
        "Ultralytics": _collect_ultralytics_info(),
        "核心依赖库": _collect_core_packages(),
    }


# 两列固定宽度。字段名最长是 "CUDA_VISIBLE_DEVICES"(20 显示宽):
#   - COL_KEY   字段列:取 20(想更紧凑就调小,如 14)。
#   - COL_VALUE 值列:值右对齐的宽度。值都已在各 collector 里尽量做短(CPU 型号取
#                真实型号名、GPU 列表只留型号),一行放得下;万一某值仍超宽会向左
#                溢出,把这个数调大即可。
COL_KEY: int = 20
COL_VALUE: int = 50


def format_system_info(
    snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
    title: str = "环境快照 ENVIRONMENT SNAPSHOT",
) -> str:
    """把快照渲染为两列:字段(左对齐) / 值(右对齐),列宽写死,不折行。

    每个区块用一行 `【区块名】` 当小标题(不占列),下接一条分隔线和若干 `字段  值` 行;
    列宽由模块常量 COL_KEY / COL_VALUE 设定,风格与 init_project.py 的目录表一致。
        - 不折行:值都已在各 collector 里做短(CPU 型号取真实型号名、GPU 列表只留型号),
          一行放得下;万一仍超宽则向左溢出(把 COL_VALUE 调大即可)。
        - list 型值(多张 GPU)逐项展开,每项各占一行,字段名只在首行出现。

    Args:
        snapshot: collect_system_info() 的结果;为 None 时内部自行采集。
        title: 顶部标题。

    Returns:
        多行字符串,可直接 print 或写入文件 / 报告。
    """
    if snapshot is None:
        snapshot = collect_system_info()

    widths = [COL_KEY, COL_VALUE]
    aligns = ["left", "right"]                   # 字段左对齐、值右对齐
    total = sum(widths) + len(widths) - 1        # 表宽 = 分隔线 / 横幅长度

    lines: List[str] = []
    lines.append("=" * total)
    lines.append(pad_to_width(title, total, align="center"))
    lines.append("=" * total)

    for name, fields in snapshot.items():
        lines.append("")
        lines.append(f"【{name}】")
        lines.append(format_table_separator(widths))
        for key, value in fields.items():
            # list 型值逐项一行(字段名只在首行);标量值就一行
            items = [str(v) for v in value] if isinstance(value, list) else [str(value)]
            items = items or [""]
            lines.append(format_table_row([key, items[0]], widths, aligns).rstrip())
            for extra in items[1:]:
                lines.append(format_table_row(["", extra], widths, aligns).rstrip())

    lines.append("")
    lines.append("=" * total)
    return "\n".join(lines)


def log_system_info(
    logger_instance: Optional[logging.Logger] = None,
    snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """采集(或复用)环境快照并逐行写入日志,返回快照字典。

    逐行 logger.info 输出,与 logging_utils 初始化 banner 风格一致;
    项目控制台格式前缀是定宽的(level/filename/lineno 都做了 padding),
    所以逐行打印依然保持表格对齐。

    Args:
        logger_instance: 指定 logger;为 None 时用本模块 logger(冒泡到根 logger)。
        snapshot: 已有快照;为 None 时内部采集。

    Returns:
        采集到的快照字典(便于调用方进一步序列化 / 入库)。
    """
    log = logger_instance or logger
    if snapshot is None:
        snapshot = collect_system_info()
    for line in format_system_info(snapshot).splitlines():
        log.info(line)
    return snapshot


def system_info_to_json(
    snapshot: Optional[Dict[str, Dict[str, Any]]] = None,
    indent: int = 2,
) -> str:
    """把快照序列化为 JSON 字符串(训练复现常用:写进 run 的 meta 文件)。"""
    if snapshot is None:
        snapshot = collect_system_info()
    return json.dumps(snapshot, ensure_ascii=False, indent=indent)


if __name__ == "__main__":
    # 自测:仅依赖 stdlib + string_utils。真实项目中由 CLI 入口的 get_logger()
    # 统一装配 handler;这里临时配一个 console handler 以便看到逐行输出效果。
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(filename)-18s:%(lineno)-4d │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    snap = log_system_info()

    print("\n--- system_info_to_json() 片段(可写入 run 元数据用于复现)---")
    print(system_info_to_json(snap)[:700] + "\n  ...")