"""项目重置工具 —— 将项目恢复到初始化状态。

用法:
    python scripts/reset_project.py --level logs
    python scripts/reset_project.py --level runtime --dry-run
    python scripts/reset_project.py --level full --yes

安全设计:
    - 硬编码白名单：源码、ADR、配置文件不可删除
    - 交互确认：默认显示摘要并要求输入 yes
    - --dry-run：预览模式，只列不删
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from pathlib import Path
from typing import List, Tuple, Set

# ── 路径初始化（与 init_project.py 完全相同）────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORM_SRC = REPO_ROOT / "apps" / "platform" / "src"
sys.path.insert(0, str(PLATFORM_SRC))

from odp_platform.common.paths import (
    ROOT_DIR,
    LOGGING_DIR,
    DATA_DIR,
    MODELS_DIR,
    RUNS_DIR,
    CONFIGS_DIR,
    PRETRAINED_MODELS_DIR,
    CHECKPOINTS_DIR,
    RAW_DATA_DIR,
    TRAIN_DIR,
    VAL_DIR,
    TEST_DIR,
    TRAIN_IMAGES_DIR,
    TRAIN_LABELS_DIR,
    VAL_IMAGES_DIR,
    VAL_LABELS_DIR,
    TEST_IMAGES_DIR,
    TEST_LABELS_DIR,
    DOCS_DIR,
    SCRIPTS_DIR,
    APP_DIR,
)
from odp_platform.cli.init_project import initialize_project
from odp_platform.common.logging_utils import get_logger


# ═══════════════════════════════════════════════════════════════════════════
# 白名单：绝对不可删除的路径
# ═══════════════════════════════════════════════════════════════════════════

# 每个条目是 (匹配方式, 模式)，匹配方式:
#   "exact"  — 精确匹配相对路径（如 "docs" 匹配 ROOT_DIR/docs）
#   "prefix" — 前缀匹配（如 "apps/platform/src" 匹配其下所有文件）
#   "glob"   — fnmatch 模式（如 "**/README.md"）
# 匹配时，路径统一转为相对于 ROOT_DIR 的 POSIX 风格字符串

WHITELIST: List[Tuple[str, str]] = [
    # ── 工作区标记与 Git ──
    ("exact", ".odp-workspace"),
    ("exact", ".gitignore"),
    ("prefix", ".git"),

    # ── 项目配置文件 ──
    ("exact", "pyproject.toml"),
    ("glob", "apps/*/pyproject.toml"),

    # ── 所有 README ──
    ("glob", "**/README.md"),

    # ── 平台源码 ──
    ("prefix", "apps/platform/src"),

    # ── 各端源码 ──
    ("prefix", "apps/desktop"),
    ("prefix", "apps/web-backend"),
    ("prefix", "apps/web-frontend"),

    # ── 共享包源码 ──
    ("prefix", "packages"),

    # ── 测试代码 ──
    ("prefix", "tests"),              # 顶层 E2E 测试
    ("prefix", "apps/platform/tests"), # Platform 单元测试

    # ── 文档（含 ADR） ──
    ("prefix", "docs"),

    # ── 工程脚本 ──
    ("prefix", "scripts"),

    # ── IDE 配置（虽然 .gitignore 了，但如果在就要保护） ──
    ("exact", ".idea"),
    ("exact", ".vscode"),
]


def _rel_path(path: Path) -> str:
    """将绝对路径转为相对于 ROOT_DIR 的 POSIX 字符串。"""
    try:
        return path.resolve().relative_to(ROOT_DIR.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def is_protected(path: Path) -> bool:
    """检查路径是否命中白名单。

    Args:
        path: 要检查的绝对路径

    Returns:
        True 表示受保护，不可删除
    """
    rel = _rel_path(path)
    for method, pattern in WHITELIST:
        if method == "exact":
            if rel == pattern or rel.startswith(pattern + "/"):
                return True
        elif method == "prefix":
            if rel == pattern or rel.startswith(pattern + "/"):
                return True
        elif method == "glob":
            if fnmatch.fnmatch(rel, pattern):
                return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 可删除项收集
# ═══════════════════════════════════════════════════════════════════════════

# ── 各级别对应的可删除目录列表 ──
RUNTIME_DELETABLE_DIRS: List[Path] = [
    DATA_DIR,
    MODELS_DIR,
    RUNS_DIR,
    CONFIGS_DIR,
]


def _collect_log_files(logger: logging.Logger) -> List[Tuple[Path, int]]:
    """收集 LOGGING_DIR 下所有 .log 文件。

    Returns:
        [(文件路径, 文件大小字节数), ...] 按路径排序
    """
    files: List[Tuple[Path, int]] = []
    if not LOGGING_DIR.exists():
        return files
    for p in sorted(LOGGING_DIR.rglob("*.log")):
        if p.is_file():
            size = p.stat().st_size
            files.append((p, size))
    logger.info(f"  扫描日志目录: {len(files)} 个 .log 文件")
    return files


def _collect_dir_contents(
    dir_path: Path, logger: logging.Logger
) -> List[Tuple[Path, int]]:
    """递归收集目录下所有可删除的文件和子目录。

    跳过白名单保护项。返回 [(路径, 大小), ...]，目录大小为 0。
    返回列表按 "文件在前、目录在后" 排序（删除时先文件后目录）。
    rglob("*") 同时返回文件和目录（包括空目录）。
    """
    if not dir_path.exists():
        return []

    files: List[Tuple[Path, int]] = []
    dirs: List[Tuple[Path, int]] = []

    for p in sorted(dir_path.rglob("*")):
        if is_protected(p):
            logger.warning(f"  ⚠ 跳过受保护项: {_rel_path(p)}")
            continue
        if p.is_file():
            files.append((p, p.stat().st_size))
        elif p.is_dir():
            dirs.append((p, 0))

    # 文件按路径排序；目录按深度降序（子目录先于父目录）
    files.sort(key=lambda x: x[0].as_posix())
    dirs.sort(key=lambda x: -len(x[0].as_posix().split("/")))

    return files + dirs


def collect_deletable(
    level: str, logger: logging.Logger
) -> Tuple[List[Tuple[Path, int]], List[Tuple[Path, str]]]:
    """根据级别收集所有可删除项。

    Args:
        level: "logs" | "runtime" | "full"
        logger: 日志记录器

    Returns:
        (待删除列表, 受保护跳过列表)
        待删除列表: [(路径, 字节大小), ...]
        受保护列表: [(路径, 原因), ...]
    """
    to_delete: List[Tuple[Path, int]] = []
    protected: List[Tuple[Path, str]] = []

    if level == "logs":
        # ── 仅日志文件 ──
        log_files = _collect_log_files(logger)
        for p, size in log_files:
            if is_protected(p):
                protected.append((p, "白名单保护"))
            else:
                to_delete.append((p, size))

    elif level == "runtime":
        # ── 日志文件 + 运行时产物目录内容 ──
        log_files = _collect_log_files(logger)
        for p, size in log_files:
            if is_protected(p):
                protected.append((p, "白名单保护"))
            else:
                to_delete.append((p, size))

        for dir_path in RUNTIME_DELETABLE_DIRS:
            if not dir_path.exists():
                continue
            items = _collect_dir_contents(dir_path, logger)
            to_delete.extend(items)

    elif level == "full":
        # ── 日志目录全部内容（含日志文件，避免与 _collect_log_files 重复） ──
        if LOGGING_DIR.exists():
            logging_items = _collect_dir_contents(LOGGING_DIR, logger)
            to_delete.extend(logging_items)

        # ── 运行时产物目录内容 + 目录本身 ──
        for dir_path in RUNTIME_DELETABLE_DIRS:
            if not dir_path.exists():
                continue
            items = _collect_dir_contents(dir_path, logger)
            to_delete.extend(items)
            if not is_protected(dir_path):
                to_delete.append((dir_path, 0))

    return to_delete, protected


# ═══════════════════════════════════════════════════════════════════════════
# 显示与确认
# ═══════════════════════════════════════════════════════════════════════════

LINE_WIDTH: int = 80


def _fmt_size(size_bytes: int) -> str:
    """人类可读的文件大小。"""
    if size_bytes == 0:
        return "0 B"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TiB"


def display_summary(
    to_delete: List[Tuple[Path, int]],
    protected: List[Tuple[Path, str]],
    level: str,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    """显示删除摘要。

    Args:
        to_delete: 待删除项列表
        protected: 受保护项列表
        level: 重置级别
        dry_run: 是否为预览模式
        logger: 日志记录器
    """
    mode = "预览模式 (--dry-run)" if dry_run else "执行模式"
    header = f" 项目重置摘要 (级别: {level}, {mode}) "
    logger.info("=" * LINE_WIDTH)
    logger.info(header.center(LINE_WIDTH, "="))
    logger.info(f"项目根目录: {ROOT_DIR}")
    logger.info("-" * LINE_WIDTH)

    if not to_delete and not protected:
        logger.info("  没有需要清理的内容，项目已处于干净状态。")
        return

    # ── 待删除 ──
    if to_delete:
        total_files = sum(1 for p, s in to_delete if s > 0 or p.is_file())
        total_dirs = sum(1 for p, s in to_delete if s == 0 and p.is_dir())
        total_size = sum(s for _, s in to_delete)

        logger.info("")
        logger.info(f"  ▶ 将删除:")
        logger.info(f"    文件: {total_files} 个")
        logger.info(f"    目录: {total_dirs} 个")
        logger.info(f"    总大小: {_fmt_size(total_size)}")
        logger.info("")
        logger.info("  详细列表:")

        # 按类别分组显示
        categories = {
            "日志文件": lambda p: p.suffix == ".log",
            "数据目录": lambda p: str(DATA_DIR) in str(p),
            "模型目录": lambda p: str(MODELS_DIR) in str(p),
            "训练产物": lambda p: str(RUNS_DIR) in str(p),
            "配置目录": lambda p: str(CONFIGS_DIR) in str(p),
        }

        shown: Set[Path] = set()
        for cat_name, cat_filter in categories.items():
            cat_items = [
                (p, s) for p, s in to_delete if cat_filter(p) and p not in shown
            ]
            if not cat_items:
                continue
            logger.info(f"    [{cat_name}]")
            for p, s in cat_items:
                rel = _rel_path(p)
                logger.info(f"      {rel}  ({_fmt_size(s)})")
                shown.add(p)

        # 未归类的
        uncat = [(p, s) for p, s in to_delete if p not in shown]
        if uncat:
            logger.info(f"    [其他]")
            for p, s in uncat:
                logger.info(f"      {_rel_path(p)}  ({_fmt_size(s)})")

    # ── 受保护（跳过的） ──
    if protected:
        logger.info("")
        logger.info(f"  ⊘ 将保留 (受白名单保护): {len(protected)} 项")
        # 只显示目录级别的受保护项摘要
        protected_dirs: Set[str] = set()
        for p, _ in protected:
            protected_dirs.add(_rel_path(p))
        # 取每个顶层目录
        top_dirs: Set[str] = set()
        for d in sorted(protected_dirs):
            parts = d.split("/")
            if len(parts) >= 1:
                top_dirs.add(parts[0] if len(parts) == 1 else "/".join(parts[:2]))
        for d in sorted(top_dirs):
            logger.info(f"    {d}/  (及其所有内容)")

    logger.info("-" * LINE_WIDTH)


def confirm_action(skip_prompt: bool) -> bool:
    """请求用户确认。

    Args:
        skip_prompt: True 则跳过提示直接返回 True

    Returns:
        True 表示用户确认继续
    """
    if skip_prompt:
        return True
    try:
        response = input("\n  输入 'yes' 确认执行删除: ").strip()
        return response == "yes"
    except (KeyboardInterrupt, EOFError):
        print("\n  已取消。")
        return False
