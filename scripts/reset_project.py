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
