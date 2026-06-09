#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : paths.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : 集中定义项目路径常量
#              - 使用 marker file 模式定位 ROOT_DIR(workspace 根)
#              - 引入 APP_DIR 概念,把【共享资产】和【端私有资产】分开

from pathlib import Path
from typing import List, Tuple

# ============================================================
# Workspace 根目录定位 (marker file 模式)
# ============================================================
WORKSPACE_MARKER: str = ".odp-workspace"


def _find_workspace_root(
    start: Path,
    markers: Tuple[str, ...] = (WORKSPACE_MARKER,),
) -> Path:
    """
    从 start 开始沿父目录向上查找,返回包含任一 marker 文件的目录。

    Args:
        start: 起始路径(通常是 Path(__file__))
        markers: 一组 marker 文件名,任一存在即视为找到

    Returns:
        Path: workspace 根目录

    Raises:
        FileNotFoundError: 一直爬到文件系统根仍没找到
    """
    current = start.resolve()
    if current.is_file():
        current = current.parent

    for parent in [current, *current.parents]:
        for marker in markers:
            if (parent / marker).exists():
                return parent

    raise FileNotFoundError(
        f"找不到 workspace marker 文件 ({markers})。"
        f"请确认仓库根存在 {WORKSPACE_MARKER} 文件。"
    )


# 计算 ROOT_DIR(模块加载时执行一次)
ROOT_DIR: Path = _find_workspace_root(Path(__file__))


# ============================================================
# 端根目录 APP_DIR (platform 这一个端的根)
# ============================================================
APP_DIR: Path = ROOT_DIR / "apps" / "platform"


# ============================================================
# 【共享资产】(在 ROOT_DIR 下,所有端可访问)
# ============================================================
DATA_DIR: Path = ROOT_DIR / "data"
MODELS_DIR: Path = ROOT_DIR / "models"
RUNS_DIR: Path = ROOT_DIR / "runs"

# 模型子目录
PRETRAINED_MODELS_DIR: Path = MODELS_DIR / "pretrained"
CHECKPOINTS_DIR: Path = MODELS_DIR / "checkpoints"

# 数据集子目录
RAW_DATA_DIR: Path = DATA_DIR / "raw"

TRAIN_DIR: Path = DATA_DIR / "train"
VAL_DIR: Path = DATA_DIR / "val"
TEST_DIR: Path = DATA_DIR / "test"

TRAIN_IMAGES_DIR: Path = TRAIN_DIR / "images"
TRAIN_LABELS_DIR: Path = TRAIN_DIR / "labels"
VAL_IMAGES_DIR: Path = VAL_DIR / "images"
VAL_LABELS_DIR: Path = VAL_DIR / "labels"
TEST_IMAGES_DIR: Path = TEST_DIR / "images"
TEST_LABELS_DIR: Path = TEST_DIR / "labels"


# ============================================================
# 【端私有资产】(在 APP_DIR 下,只属于 platform 这个端)
# ============================================================
CONFIGS_DIR: Path = APP_DIR / "configs"
LOGGING_DIR: Path = APP_DIR / "logging"
UNIT_TEST_DIR: Path = APP_DIR / "tests"


# ============================================================
# 【顶层文档目录】(共享给所有人)
# ============================================================
DOCS_DIR: Path = ROOT_DIR / "docs"


# ============================================================
# 【工程基础设施目录】(共享)
# ============================================================
SCRIPTS_DIR: Path = ROOT_DIR / "scripts"


# 引入META_LOGGING_DIR
META_DIR: Path = ROOT_DIR / ".odp-meta"
META_LOGGING_DIR: Path = META_DIR / "logs"

# D3新增： 数据集配置目录 + 路径辅助函数
DATASET_CONFIGS_DIR: Path = CONFIGS_DIR / "datasets"

def raw_dataset_root(dataset_name: str) -> Path:
    """
    返回某个数据集的raw跟目录
    """
    return RAW_DATA_DIR / dataset_name

def dataset_yaml_path(dataset_name: str) -> Path:
    """
    返回某个数据集的配置文件路径
    """
    return DATASET_CONFIGS_DIR / f"{dataset_name}.yaml"


# ============================================================
# 对外暴露的"要初始化的目录列表"
# ============================================================
def get_dirs_to_initialize() -> List[Path]:
    """
    返回项目启动时需要确保存在的所有目录列表。

    这是 init_project.py 的【唯一数据源】——
    paths.py 决定要哪些目录,init_project 只负责创建。

    Returns:
        所有需要初始化的目录路径列表
    """
    return [
        # 共享资产
        DATA_DIR,
        RUNS_DIR,
        MODELS_DIR,
        PRETRAINED_MODELS_DIR,
        CHECKPOINTS_DIR,
        RAW_DATA_DIR,
        TRAIN_IMAGES_DIR,
        TRAIN_LABELS_DIR,
        VAL_IMAGES_DIR,
        VAL_LABELS_DIR,
        TEST_IMAGES_DIR,
        TEST_LABELS_DIR,
        # 端私有资产
        CONFIGS_DIR,
        LOGGING_DIR,
        UNIT_TEST_DIR,
        # 工程基础设施
        SCRIPTS_DIR,
        DOCS_DIR,
        # 元数据目录
        META_LOGGING_DIR
    ]

def get_dirs_to_reset() -> List[Path]:
    """
    返回reset_project 可以安全清理的目录列表
    可以被反向清理的运行是产物目录-绝对不能包含git追踪的目录

    Returns:
        所有可以被reset_project安全清理的目录列表
    """
    return [
        # 划分后的数据集
        TRAIN_DIR,
        VAL_DIR,
        TEST_DIR,

        # 训练时的产物
        RUNS_DIR,
        CHECKPOINTS_DIR,
        # 端私有运行时日志
        LOGGING_DIR,
        # 配置文件是自动的生成的，可以删除
        CONFIGS_DIR,
    ]

# 绝对保护目录reset工具永远不能删除这些目录
PROTECTED_DIRS: tuple[Path, ...] = (
    ROOT_DIR,
    ROOT_DIR / "apps",
    ROOT_DIR / "packages",
    APP_DIR,
    APP_DIR / "src",
    SCRIPTS_DIR,
    DOCS_DIR,
    UNIT_TEST_DIR,
    ROOT_DIR / ".git",
    ROOT_DIR / ".odp-workspace",
    META_DIR,
    META_LOGGING_DIR
)

def is_protected(path: Path) -> bool:
    """
    判断给定路径是否是绝对保护目录，绝对保护目录不能被reset_project清理

    Returns:
        True: 是绝对保护目录
        False: 不是绝对保护目录
    """
    path = path.resolve(strict=False)
    for protected in PROTECTED_DIRS:
        protected_resolved = protected.resolve(strict=False)
        if path == protected_resolved:
            return True
        # 保护目录是 path 的子目录 → path 是保护目录的祖先 (试图删除父目录)
        if protected_resolved.is_relative_to(path):
            return True
        # path 是保护目录的子目录 → path 在保护目录内部 (试图删除子目录)
        if path.is_relative_to(protected_resolved):
            return True
    return False


if __name__ == "__main__":
    print(f"ROOT_DIR (workspace) = {ROOT_DIR}")
    print(f"APP_DIR  (platform)  = {APP_DIR}")
    print(f"\n共享资产:")
    print(f"  DATA_DIR    = {DATA_DIR.relative_to(ROOT_DIR)}")
    print(f"  MODELS_DIR  = {MODELS_DIR.relative_to(ROOT_DIR)}")
    print(f"  RUNS_DIR    = {RUNS_DIR.relative_to(ROOT_DIR)}")
    print(f"\n端私有资产:")
    print(f"  CONFIGS_DIR = {CONFIGS_DIR.relative_to(ROOT_DIR)}")
    print(f"  LOGGING_DIR = {LOGGING_DIR.relative_to(ROOT_DIR)}")

    print(f"\n要初始化的目录共 {len(get_dirs_to_initialize())} 个:")
    for d in get_dirs_to_initialize():
        print(f"  - {d.relative_to(ROOT_DIR)}")