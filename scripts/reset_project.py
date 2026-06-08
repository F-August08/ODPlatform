"""项目重置工具 —— 清理运行时产物，可选重新初始化。

用法:
    python scripts/reset_project.py --level logs
    python scripts/reset_project.py --level runtime --dry-run
    python scripts/reset_project.py --level full --yes --reinit

安全设计:
    - 硬编码白名单：源码、ADR、配置文件、初始化日志不可删除
    - 删除与重新初始化分为两个独立步骤
    - 交互确认：默认显示摘要并要求输入 yes
    - --dry-run：预览模式，只列不删
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
import sys
from pathlib import Path
from typing import List, Optional, Tuple, Set

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

    # ── 重置操作审计日志（保留每次删除操作的记录） ──
    ("prefix", "apps/platform/logging/Reset_project"),
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
            logger.warning(f"  [!] 跳过受保护项: {_rel_path(p)}")
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


def confirm_action(skip_prompt: bool, logger: logging.Logger) -> bool:
    """请求用户二次确认。

    Args:
        skip_prompt: True 则跳过提示直接返回 True
        logger: 日志记录器

    Returns:
        True 表示用户确认继续，False 表示取消
    """
    if skip_prompt:
        return True
    try:
        response = input("\n  确认执行删除？[yes/no]: ").strip().lower()
        if response == "yes":
            return True
        elif response == "no":
            logger.info("  已撤销，未做任何更改。")
            return False
        else:
            logger.warning(f"  无效输入 '{response}'，请输入 yes 或 no。操作已取消。")
            return False
    except (KeyboardInterrupt, EOFError):
        logger.info("")
        logger.info("  已取消。")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 删除执行
# ═══════════════════════════════════════════════════════════════════════════

def execute_deletion(
    to_delete: List[Tuple[Path, int]],
    logger: logging.Logger,
) -> Tuple[int, int, List[str]]:
    """执行删除操作。

    先删文件（按路径排序），再删目录（按深度降序——子目录先于父目录）。

    Args:
        to_delete: 待删除项列表
        logger: 日志记录器

    Returns:
        (成功数, 失败数, 失败详情列表)
    """
    # 分离文件和目录
    files = [(p, s) for p, s in to_delete if p.is_file()]
    dirs = [(p, s) for p, s in to_delete if p.is_dir()]

    # 目录按深度降序：子目录更深，先删
    dirs.sort(key=lambda x: -len(x[0].as_posix().split("/")))

    success = 0
    failed = 0
    errors: List[str] = []

    # ── 先删文件 ──
    for p, size in files:
        try:
            p.unlink()
            logger.info(f"  [OK] 已删除文件: {_rel_path(p)}")
            success += 1
        except OSError as e:
            logger.error(f"  [FAIL] 删除失败: {_rel_path(p)} — {e}")
            failed += 1
            errors.append(f"{_rel_path(p)}: {e}")

    # ── 再删目录 ──
    for p, _ in dirs:
        try:
            if p.exists():
                p.rmdir()
                logger.info(f"  [OK] 已删除目录: {_rel_path(p)}")
                success += 1
        except OSError as e:
            logger.warning(f"  [!] 目录非空或删除失败: {_rel_path(p)} — {e}")
            failed += 1
            errors.append(f"{_rel_path(p)}: {e}")

    return success, failed, errors


# ═══════════════════════════════════════════════════════════════════════════
# CLI 主入口
# ═══════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="ODPlatform 项目重置工具 —— 清理运行时产物，可选重新初始化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/reset_project.py --level logs
  python scripts/reset_project.py --level runtime --dry-run
  python scripts/reset_project.py --level full --yes --reinit
        """,
    )
    parser.add_argument(
        "--level",
        choices=["logs", "runtime", "full"],
        help="清理级别: logs=仅日志, runtime=日志+数据+模型+训练产物, full=全部清理（不指定则交互选择）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式，仅列出将删除的内容，不执行任何删除",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="跳过确认提示，直接执行（适用于 CI/脚本化）",
    )
    parser.add_argument(
        "--reinit",
        action="store_true",
        help="删除后自动重新初始化项目目录（CLI 模式下配合 --yes 使用）",
    )
    return parser


# ═══════════════════════════════════════════════════════════════════════════
# 交互式级别选择
# ═══════════════════════════════════════════════════════════════════════════

def _interactive_select_level(logger: logging.Logger) -> Optional[str]:
    """交互式选择重置级别。

    Args:
        logger: 日志记录器

    Returns:
        "logs" | "runtime" | "full" | None (用户取消)
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("  ODPlatform 项目重置工具")
    logger.info("=" * 60)
    logger.info("")
    logger.info("  请选择清理级别:")
    logger.info("")
    logger.info("    A — 仅清理日志文件")
    logger.info("        删除 apps/platform/logging/ 下的 .log 文件")
    logger.info("        （保留 Reset_project 审计日志）")
    logger.info("")
    logger.info("    B — 清理日志 + 运行时产物")
    logger.info("        删除日志 + data/ + models/ + runs/ + configs/")
    logger.info("")
    logger.info("    C — 全部清理")
    logger.info("        删除以上全部可删除内容")
    logger.info("")
    logger.info("    Q — 退出")
    logger.info("")
    logger.info("-" * 60)
    logger.info("  [!] 白名单保护（无论选择哪种级别，以下内容均不可删除）:")
    logger.info("    · 源码: apps/*/src/, packages/")
    logger.info("    · 文档: docs/ (含架构决策记录 ADR)")
    logger.info("    · 测试: tests/, apps/platform/tests/")
    logger.info("    · 脚本: scripts/")
    logger.info("    · 配置: pyproject.toml, .odp-workspace, .gitignore, README.md")
    logger.info("    · 审计日志: apps/platform/logging/Reset_project/")
    logger.info("-" * 60)
    logger.info("  提示: 清理完成后可选择是否重新初始化项目目录。")
    logger.info("-" * 60)

    while True:
        try:
            choice = input("  请输入 [A/B/C/Q]: ").strip().upper()
        except (KeyboardInterrupt, EOFError):
            logger.info("")
            return None

        if choice == "A":
            return "logs"
        elif choice == "B":
            return "runtime"
        elif choice == "C":
            return "full"
        elif choice == "Q":
            return None
        else:
            logger.warning(f"  无效选项 '{choice}'，请输入 A、B、C 或 Q")


def main() -> None:
    """主入口。"""
    parser = build_parser()
    args = parser.parse_args()

    # ── 1. 初始化日志（必须在删除操作之前） ──
    logger = get_logger(
        base_path=LOGGING_DIR,
        log_type="Reset_project",
        temp_log=False,
    )
    logger.info("=" * LINE_WIDTH)
    logger.info("ODPlatform 项目重置工具".center(LINE_WIDTH))
    logger.info("=" * LINE_WIDTH)

    try:
        _run_reset(args, logger)
    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("=" * LINE_WIDTH)
        logger.warning("  用户中断 (Ctrl+C) — 操作未完成".center(LINE_WIDTH))
        logger.warning("=" * LINE_WIDTH)
        logger.warning("  重置工具是幂等的，重新运行相同命令即可安全完成。")
        logger.warning("=" * LINE_WIDTH)


def _run_reset(args: argparse.Namespace, logger: logging.Logger) -> None:
    """执行重置流程的核心逻辑。"""

    # ── 2. 确定重置级别（命令行指定 或 交互选择） ──
    level = args.level
    if level is None:
        level = _interactive_select_level(logger)
        if level is None:
            logger.info("已取消。")
            return

    logger.info(f"级别: {level} | 模式: {'预览' if args.dry_run else '执行'} | 跳过确认: {'是' if args.yes else '否'}")
    logger.info("=" * LINE_WIDTH)

    # ── 2. 收集 ──
    logger.info("")
    logger.info("[阶段 1/4] 扫描可删除项...")
    to_delete, protected = collect_deletable(level, logger)

    # ── 3. 显示摘要 ──
    logger.info("")
    logger.info("[阶段 2/4] 生成删除摘要...")
    display_summary(to_delete, protected, level, args.dry_run, logger)

    if not to_delete:
        logger.info("没有需要清理的内容。")
        _maybe_reinitialize(args, logger)
        return

    # ── 4. dry-run 到此结束 ──
    if args.dry_run:
        logger.info("")
        logger.info("[预览模式] 以上内容不会被实际删除。移除 --dry-run 以执行。")
        return

    # ── 5. 确认 ──
    logger.info("")
    logger.info("[阶段 3/4] 等待用户确认...")
    if not confirm_action(args.yes, logger):
        logger.info("已取消操作，未做任何更改。")
        return

    # ── 6. 执行删除（先关闭文件日志句柄，释放 Windows 文件锁） ──
    logger.info("")
    logger.info("[阶段 4/4] 执行删除...")
    logger.info("-" * LINE_WIDTH)

    # 关闭所有 FileHandler，释放当前日志文件的句柄
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    for fh in file_handlers:
        logger.removeHandler(fh)
        fh.close()

    interrupted = False
    success, failed, errors = 0, 0, []
    try:
        success, failed, errors = execute_deletion(to_delete, logger)
    except KeyboardInterrupt:
        interrupted = True
        logger.warning("")
        logger.warning("=" * LINE_WIDTH)
        logger.warning("  用户中断 (Ctrl+C) — 删除操作未完成".center(LINE_WIDTH))
        logger.warning("=" * LINE_WIDTH)
        logger.warning("  部分文件可能已被删除，但操作是幂等的：")
        logger.warning("  重新运行相同命令即可安全完成清理。")
        logger.warning("=" * LINE_WIDTH)

    # ── 7. 输出汇总 ──
    logger.info("")
    logger.info("=" * LINE_WIDTH)
    logger.info("清理完成".center(LINE_WIDTH))
    logger.info(f"  成功: {success} 项")
    if failed:
        logger.warning(f"  失败: {failed} 项")
        for err in errors:
            logger.warning(f"    - {err}")
    logger.info("=" * LINE_WIDTH)

    if interrupted:
        return

    # ── 8. 重新初始化（独立的可选步骤） ──
    _maybe_reinitialize(args, logger)


def _maybe_reinitialize(args: argparse.Namespace, logger: logging.Logger) -> None:
    """询问用户是否重新初始化项目目录。

    CLI 模式: --reinit 标志控制；交互模式: 提示用户选择。
    """
    do_reinit = False

    if args.reinit:
        # CLI 明确指定
        do_reinit = True
    elif not args.yes:
        # 交互模式：询问用户
        try:
            response = input("\n  是否重新初始化项目目录？[yes/no]: ").strip().lower()
            if response == "yes":
                do_reinit = True
            elif response == "no":
                logger.info("  跳过重新初始化。")
                logger.info("  可稍后手动运行: python scripts/init_project.py")
            else:
                logger.info(f"  无效输入，跳过重新初始化。")
                logger.info("  可稍后手动运行: python scripts/init_project.py")
        except (KeyboardInterrupt, EOFError):
            logger.info("")
            logger.info("  已取消，跳过重新初始化。")
            return

    if not do_reinit:
        return

    logger.info("")
    logger.info("=" * LINE_WIDTH)
    logger.info("重新初始化项目...".center(LINE_WIDTH))
    logger.info("=" * LINE_WIDTH)
    try:
        initialize_project()
        logger.info("重新初始化完成。")
    except KeyboardInterrupt:
        logger.warning("初始化被中断。请手动运行: python scripts/init_project.py")
    except Exception as e:
        logger.error(f"重新初始化失败: {e}")
        logger.error("请手动运行: python scripts/init_project.py")


if __name__ == "__main__":
    main()
