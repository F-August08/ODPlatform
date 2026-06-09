# 项目重置工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `scripts/reset_project.py`，支持三级重置（logs/runtime/full），带白名单保护和交互确认。

**Architecture:** 单文件 CLI 脚本，遵循 `scripts/init_project.py` 的模式。复用 `odp_platform.common.paths` 的路径定义、`odp_platform.cli.init_project.initialize_project()` 和 `odp_platform.common.logging_utils.get_logger()`。使用 argparse 解析参数，硬编码白名单保护源码/文档/配置。

**Tech Stack:** Python 3.10+，仅标准库（argparse, pathlib, shutil, fnmatch, logging）

---

### Task 1: 创建白名单模块级常量与匹配函数

**Files:**
- Create: `scripts/reset_project.py`

- [ ] **Step 1: 写出白名单定义和匹配函数**

```python
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
```

- [ ] **Step 2: 验证白名单可被导入**

Run: `cd /d/Demo/python/ODplatform && python -c "import sys; sys.path.insert(0, 'apps/platform/src'); from scripts.reset_project import WHITELIST, is_protected; print(f'白名单条目: {len(WHITELIST)}'); print(f'docs 受保护: {is_protected(Path(\"docs\"))}')"`

Expected: 白名单条目: 17, docs 受保护: True

- [ ] **Step 3: Commit**

```bash
git add scripts/reset_project.py
git commit -m "feat(reset): add whitelist constants and matching function"
```

---

### Task 2: 实现可删除项收集函数

**Files:**
- Modify: `scripts/reset_project.py`（追加内容）

- [ ] **Step 1: 写出三个级别的收集函数和主收集入口**

在文件末尾追加以下代码（`is_protected` 函数之后）:

```python
# ═══════════════════════════════════════════════════════════════════════════
# 可删除项收集
# ═══════════════════════════════════════════════════════════════════════════

# ── 各级别对应的可删除目录列表 ──
# 注意：这些目录本身也在 init 时创建，full 级别会连目录一起删

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
    items: List[Tuple[Path, int]] = []
    if not dir_path.exists():
        return items

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

    # 文件按路径排序；目录按深度降序（子目录先于父目录，确保删除父目录时已空）
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

    # ── 日志文件（所有级别都包含） ──
    log_files = _collect_log_files(logger)
    for p, size in log_files:
        if is_protected(p):
            protected.append((p, "白名单保护"))
        else:
            to_delete.append((p, size))

    if level in ("runtime", "full"):
        # ── 运行时产物目录的内容 ──
        for dir_path in RUNTIME_DELETABLE_DIRS:
            if not dir_path.exists():
                continue
            items = _collect_dir_contents(dir_path, logger)
            to_delete.extend(items)

        if level == "full":
            # ── 删除运行时产物目录本身（在内容之后） ──
            for dir_path in RUNTIME_DELETABLE_DIRS:
                if dir_path.exists() and not is_protected(dir_path):
                    to_delete.append((dir_path, 0))
            # logging 目录：只删除内容，不删目录本身
            # （Windows 下删除 LOGGING_DIR 会因当前进程持有日志文件句柄而失败）
            if LOGGING_DIR.exists():
                logging_items = _collect_dir_contents(LOGGING_DIR, logger)
                to_delete.extend(logging_items)

    return to_delete, protected
```

- [ ] **Step 2: 验证收集逻辑**

Run: `cd /d/Demo/python/ODplatform && python -c "
import sys, logging
sys.path.insert(0, 'apps/platform/src')
from scripts.reset_project import collect_deletable, REPO_ROOT
logger = logging.getLogger('test')
logging.basicConfig(level=logging.INFO)
to_del, prot = collect_deletable('logs', logger)
print(f'待删除: {len(to_del)} 项')
print(f'受保护: {len(prot)} 项')
for p, s in to_del[:5]:
    print(f'  - {p.relative_to(REPO_ROOT)} ({s} bytes)')
"`

Expected: 列出日志文件数量（应 > 0），受保护项为 0

- [ ] **Step 3: Commit**

```bash
git add scripts/reset_project.py
git commit -m "feat(reset): add deletable items collection functions"
```

---

### Task 3: 实现摘要显示和确认函数

**Files:**
- Modify: `scripts/reset_project.py`（追加内容）

- [ ] **Step 1: 写出摘要显示和确认函数**

在文件末尾追加:

```python
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
```

- [ ] **Step 2: 验证摘要显示**

Run: `cd /d/Demo/python/ODplatform && python -c "
import sys, logging
sys.path.insert(0, 'apps/platform/src')
from scripts.reset_project import collect_deletable, display_summary, REPO_ROOT
logger = logging.getLogger('test')
logging.basicConfig(level=logging.INFO)
to_del, prot = collect_deletable('full', logger)
display_summary(to_del, prot, 'full', True, logger)
"`

Expected: 打印格式化摘要，含文件数、目录数、总大小、分类列表、受保护项

- [ ] **Step 3: Commit**

```bash
git add scripts/reset_project.py
git commit -m "feat(reset): add summary display and confirmation functions"
```

---

### Task 4: 实现删除执行函数

**Files:**
- Modify: `scripts/reset_project.py`（追加内容）

- [ ] **Step 1: 写出删除执行函数**

在文件末尾追加:

```python
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
            logger.info(f"  ✓ 已删除文件: {_rel_path(p)}")
            success += 1
        except OSError as e:
            logger.error(f"  ✗ 删除失败: {_rel_path(p)} — {e}")
            failed += 1
            errors.append(f"{_rel_path(p)}: {e}")

    # ── 再删目录 ──
    for p, _ in dirs:
        try:
            if p.exists():
                p.rmdir()  # 用 rmdir 而非 rmtree，目录应该已空
                logger.info(f"  ✓ 已删除目录: {_rel_path(p)}")
                success += 1
        except OSError as e:
            # 如果目录非空（可能有受保护文件），用 rmtree 忽略受保护项太重，
            # 这里只报告失败
            logger.warning(f"  ⚠ 目录非空或删除失败: {_rel_path(p)} — {e}")
            failed += 1
            errors.append(f"{_rel_path(p)}: {e}")

    return success, failed, errors
```

- [ ] **Step 2: Commit**

```bash
git add scripts/reset_project.py
git commit -m "feat(reset): add deletion execution function"
```

---

### Task 5: 实现 CLI 主入口与 argparse

**Files:**
- Modify: `scripts/reset_project.py`（追加内容）

- [ ] **Step 1: 写出 main() 函数和入口**

在文件末尾追加:

```python
# ═══════════════════════════════════════════════════════════════════════════
# CLI 主入口
# ═══════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="ODPlatform 项目重置工具 —— 将项目恢复到初始化状态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/reset_project.py --level logs
  python scripts/reset_project.py --level runtime --dry-run
  python scripts/reset_project.py --level full --yes
        """,
    )
    parser.add_argument(
        "--level",
        required=True,
        choices=["logs", "runtime", "full"],
        help="重置级别: logs=仅日志, runtime=日志+数据+模型+训练产物, full=全部+重新初始化",
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
    return parser


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
    logger.info(f"级别: {args.level} | 模式: {'预览' if args.dry_run else '执行'} | 跳过确认: {'是' if args.yes else '否'}")
    logger.info("=" * LINE_WIDTH)

    # ── 2. 收集 ──
    logger.info("")
    logger.info("[阶段 1/4] 扫描可删除项...")
    to_delete, protected = collect_deletable(args.level, logger)

    # ── 3. 显示摘要 ──
    logger.info("")
    logger.info("[阶段 2/4] 生成删除摘要...")
    display_summary(to_delete, protected, args.level, args.dry_run, logger)

    if not to_delete:
        logger.info("没有需要清理的内容。")
        if args.level == "full":
            logger.info("但仍将运行初始化以确保目录结构完整...")
            initialize_project()
        return

    # ── 4. dry-run 到此结束 ──
    if args.dry_run:
        logger.info("")
        logger.info("[预览模式] 以上内容不会被实际删除。移除 --dry-run 以执行。")
        return

    # ── 5. 确认 ──
    logger.info("")
    logger.info("[阶段 3/4] 等待用户确认...")
    if not confirm_action(args.yes):
        logger.info("已取消操作，未做任何更改。")
        return

    # ── 6. 执行删除 ──
    logger.info("")
    logger.info("[阶段 4/4] 执行删除...")
    logger.info("-" * LINE_WIDTH)
    success, failed, errors = execute_deletion(to_delete, logger)

    # ── 7. (仅 full) 重新初始化 ──
    if args.level == "full":
        logger.info("")
        logger.info("=" * LINE_WIDTH)
        logger.info("重新初始化项目...".center(LINE_WIDTH))
        logger.info("=" * LINE_WIDTH)
        try:
            initialize_project()
        except Exception as e:
            logger.error(f"重新初始化失败: {e}")
            logger.error("请手动运行: python scripts/init_project.py")
            sys.exit(1)

    # ── 8. 输出汇总 ──
    logger.info("")
    logger.info("=" * LINE_WIDTH)
    logger.info("重置完成".center(LINE_WIDTH))
    logger.info(f"  成功: {success} 项")
    if failed:
        logger.warning(f"  失败: {failed} 项")
        for err in errors:
            logger.warning(f"    - {err}")
    logger.info("=" * LINE_WIDTH)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 测试 --help**

Run: `cd /d/Demo/python/ODplatform && python scripts/reset_project.py --help`

Expected: 打印帮助信息，显示三个级别选项、--dry-run、--yes 参数

- [ ] **Step 3: 测试 --dry-run（logs 级别）**

Run: `cd /d/Demo/python/ODplatform && python scripts/reset_project.py --level logs --dry-run`

Expected:
- 显示日志文件数量和总大小
- 最后显示 "[预览模式] 以上内容不会被实际删除"
- 不执行任何删除
- 日志文件仍然存在

- [ ] **Step 4: 验证 logs 级别预览后文件未被删除**

Run: `cd /d/Demo/python/ODplatform && ls apps/platform/logging/Init_project/*.log 2>/dev/null | wc -l`

Expected: 日志文件数量与之前相同

- [ ] **Step 5: 测试 --dry-run（full 级别）**

Run: `cd /d/Demo/python/ODplatform && python scripts/reset_project.py --level full --dry-run`

Expected:
- 列出所有日志文件
- 列出 data/、models/、runs/、apps/platform/configs/ 的内容
- 列出受保护项（src/、docs/、scripts/、tests/ 等）
- 显示 "[预览模式]"

- [ ] **Step 6: Commit**

```bash
git add scripts/reset_project.py
git commit -m "feat(reset): add CLI main entry with argparse"
```

---

### Task 6: 端到端验证

**Files:**
- 无新建/修改

- [ ] **Step 1: 验证 logs 级别实际删除**

```bash
# 先创建一些测试日志
mkdir -p /tmp/test_reset_logs
# 记下当前日志数量
cd /d/Demo/python/ODplatform
LOG_COUNT_BEFORE=$(find apps/platform/logging -name "*.log" 2>/dev/null | wc -l)
echo "删除前日志数: $LOG_COUNT_BEFORE"
# 执行删除（需要 user input，用 yes 管道）
echo "yes" | python scripts/reset_project.py --level logs
LOG_COUNT_AFTER=$(find apps/platform/logging -name "*.log" 2>/dev/null | wc -l)
echo "删除后日志数: $LOG_COUNT_AFTER"
```

Expected: 删除后日志数应显著减少（reset 操作本身会产生新的 Reset_project 日志）

- [ ] **Step 2: 验证白名单保护（故意触碰受保护路径）**

```bash
cd /d/Demo/python/ODplatform
# 验证 full --dry-run 不会列出 src/ 下的文件
python scripts/reset_project.py --level full --dry-run 2>&1 | grep -c "apps/platform/src"
```

Expected: 0（src 不在删除列表中）

- [ ] **Step 3: 验证 full 级别完整流程**

```bash
cd /d/Demo/python/ODplatform
# 先确认 data 目录存在
ls -la data/
# 执行 full reset
echo "yes" | python scripts/reset_project.py --level full
# 确认 data 等目录被重新创建
ls -la data/
```

Expected:
- 删除前 data/ 显示子目录
- 执行后显示初始化成功信息
- data/ 目录被重新创建（带有子目录结构）

- [ ] **Step 4: 验证 scripts/reset_project.py 自身不被删除**

```bash
cd /d/Demo/python/ODplatform
# full reset 后脚本仍然存在
test -f scripts/reset_project.py && echo "PASS: reset_project.py 未被删除" || echo "FAIL: reset_project.py 被删除了!"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit --allow-empty -m "test(reset): complete end-to-end verification"
```

---

### 完成检查清单

- [ ] `--level logs` 仅删除 `.log` 文件
- [ ] `--level runtime` 删除日志 + data + models + runs + configs
- [ ] `--level full` 删除上述 + 重新初始化
- [ ] `--dry-run` 仅预览不删除
- [ ] `--yes` 跳过确认
- [ ] 白名单保护所有源码（src/、desktop/、web-backend/、web-frontend/、packages/）
- [ ] 白名单保护测试代码（tests/、apps/platform/tests/）
- [ ] 白名单保护文档（docs/）
- [ ] 白名单保护脚本（scripts/）
- [ ] 白名单保护配置文件（pyproject.toml、.odp-workspace、.gitignore、README.md）
- [ ] 无确认输入时取消操作
- [ ] 重置日志写入 `LOGGING_DIR/Reset_project/`
