# label_format Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `label_format` check，验证 YOLO 标注文件内容的格式合法性（6 项逐行检查）。

**Architecture:** 在 `constants.py` 加两个阈值常量，新建 `checks/label_format.py` 遵循 `pair_existence` 的注册 + 比例分级模式。框架自动发现新 check，无需改 registry.py 或 service.py。

**Tech Stack:** Python 3.10+ dataclasses, pathlib, typing

---

### Task 1: Add label format threshold constants

**Files:**
- Modify: `apps/platform/src/odp_platform/common/constants.py`

- [ ] **Step 1: Add constants**

在 `PAIR_MISSING_WARN_RATIO` 下面追加两个常量：

```python
LABEL_FORMAT_ERROR_RATIO: float = 0.10  # 超过 10% 的标注文件有格式错误 → ERROR
LABEL_FORMAT_WARN_RATIO:  float = 0.01  # 超过 1% → WARNING，≤1% → INFO
```

编辑位置：`constants.py` 第 113 行之后。找到：

```python
PAIR_MISSING_ERROR_RATIO: float = 0.5  # 确实缺少的图像对占比 > 0，5 此值算错误
PAIR_MISSING_WARN_RATIO: float = 0.05  # 确实缺少的图像对占比 > 0，05 此值算提醒
```

在下面插入一个空行再加两个新常量。

- [ ] **Step 2: Verify**

```bash
cd "D:/Demo/python/ODplatform" && "D:/conda/2024/envs/odplat-gpu/python.exe" -c "from odp_platform.common.constants import LABEL_FORMAT_ERROR_RATIO, LABEL_FORMAT_WARN_RATIO; print(LABEL_FORMAT_ERROR_RATIO, LABEL_FORMAT_WARN_RATIO)"
```

Expected output: `0.1 0.01`

- [ ] **Step 3: Commit**

```bash
cd "D:/Demo/python/ODplatform" && git add apps/platform/src/odp_platform/common/constants.py && git commit -m "feat: add LABEL_FORMAT_ERROR_RATIO and LABEL_FORMAT_WARN_RATIO constants"
```

---

### Task 2: Create label_format.py check

**Files:**
- Create: `apps/platform/src/odp_platform/data_validation/checks/label_format.py`

- [ ] **Step 1: Create the complete check file**

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :label_format.py
# @Time      :2026/6/10
# @Author    :ODPlatform team
# @Project   :ODPlatform
# @Function  :label_format check — 验证 YOLO 标注文件内容的逐行格式合法性
"""label_format check — 验证 YOLO 标注文件里每一行的格式。

检查项 (6 项, 短路: 一行遇到第一个错误就记录, 不再继续):
    1. 列数           — len(parts) != 5
    2. 数值类型       — 任一列不能 parse 为 float
    3. class_id 整数  — int(cls) != cls 或 cls < 0
    4. 坐标范围       — x_center / y_center 不在 [0, 1]
    5. 宽高 > 0       — width <= 0 或 height <= 0
    6. 宽高 <= 1      — width > 1 或 height > 1

异常:
    - 文件读取失败 (权限/编码) → file_read_error, 不抛异常
    - 空文件 → 不算错
    - 空行/纯空白行 → 静默跳过
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from odp_platform.common.constants import (
    LABEL_FORMAT_ERROR_RATIO,
    LABEL_FORMAT_WARN_RATIO,
)
from odp_platform.data_validation.registry import (
    check, CheckContext, CheckResult, CheckSeverity,
)

# ---------------------------------------------------------------
# 错误类型常量
# ---------------------------------------------------------------
WRONG_COLUMN_COUNT      = "wrong_column_count"
NON_NUMERIC             = "non_numeric"
CLASS_NOT_INTEGER       = "class_not_integer"
COORD_OUT_OF_RANGE      = "coordinate_out_of_range"
DIMENSION_ZERO_OR_NEG   = "dimension_zero_or_negative"
DIMENSION_EXCEEDS_ONE   = "dimension_exceeds_one"
FILE_READ_ERROR         = "file_read_error"

DETAILS_PREVIEW_LIMIT: int = 10


# ---------------------------------------------------------------
# 单行校验 (纯函数, 无副作用)
# ---------------------------------------------------------------

def _validate_line(line: str, line_no: int) -> Optional[Tuple[str, str]]:
    """校验单行 YOLO 标注.

    Args:
        line: 已 strip 的非空行
        line_no: 行号 (从 1 开始, 仅用于错误报告)

    Returns:
        None — 该行合法
        (error_type, raw_line) — 该行有格式错误 (短路: 第一个错误)
    """
    raw_line = line
    parts = line.split()

    # 1. 列数
    if len(parts) != 5:
        return (WRONG_COLUMN_COUNT, raw_line)

    # 2. 数值类型
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return (NON_NUMERIC, raw_line)

    cls_id, x_center, y_center, width, height = values

    # 3. class_id 整数且非负
    if cls_id != int(cls_id) or cls_id < 0:
        return (CLASS_NOT_INTEGER, raw_line)

    # 4. 坐标范围 [0, 1]
    if not (0.0 <= x_center <= 1.0 and 0.0 <= y_center <= 1.0):
        return (COORD_OUT_OF_RANGE, raw_line)

    # 5. 宽高 > 0
    if width <= 0.0 or height <= 0.0:
        return (DIMENSION_ZERO_OR_NEG, raw_line)

    # 6. 宽高 <= 1
    if width > 1.0 or height > 1.0:
        return (DIMENSION_EXCEEDS_ONE, raw_line)

    return None


# ---------------------------------------------------------------
# 标注文件校验
# ---------------------------------------------------------------

def _validate_one_label(label_path) -> Tuple[bool, int, int, Dict[str, int], List[Dict[str, Any]]]:
    """校验单个标注文件的所有行.

    Returns:
        (has_error, total_lines, bad_lines, error_counts, bad_examples)
        - has_error:     该文件是否存在任何错误
        - total_lines:   该文件的非空行数
        - bad_lines:     该文件的坏行数
        - error_counts:  该文件的错误类型计数 (6 种 error_type → count)
        - bad_examples:  该文件的坏样本 (受 DETAILS_PREVIEW_LIMIT 限制)
    """
    has_error = False
    total_lines = 0
    bad_lines = 0
    error_counts: Dict[str, int] = {
        WRONG_COLUMN_COUNT: 0,
        NON_NUMERIC: 0,
        CLASS_NOT_INTEGER: 0,
        COORD_OUT_OF_RANGE: 0,
        DIMENSION_ZERO_OR_NEG: 0,
        DIMENSION_EXCEEDS_ONE: 0,
    }
    bad_examples: List[Dict[str, Any]] = []

    try:
        content = label_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return (
            True, 0, 1,
            {k: (1 if k == FILE_READ_ERROR else 0) for k in [
                WRONG_COLUMN_COUNT, NON_NUMERIC, CLASS_NOT_INTEGER,
                COORD_OUT_OF_RANGE, DIMENSION_ZERO_OR_NEG, DIMENSION_EXCEEDS_ONE,
                FILE_READ_ERROR,
            ]},
            [{"file": str(label_path), "line_no": 0, "raw_line": str(e), "error_type": FILE_READ_ERROR}],
        )

    for line_no, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:          # 跳过空行/纯空白行
            continue
        total_lines += 1

        err = _validate_line(line, line_no)
        if err is not None:
            error_type, raw_line = err
            has_error = True
            bad_lines += 1
            error_counts[error_type] += 1
            if len(bad_examples) < DETAILS_PREVIEW_LIMIT:
                bad_examples.append({
                    "file":       str(label_path),
                    "line_no":    line_no,
                    "raw_line":   raw_line,
                    "error_type": error_type,
                })

    return (has_error, total_lines, bad_lines, error_counts, bad_examples)


# ---------------------------------------------------------------
# 注册的 check 入口
# ---------------------------------------------------------------

@check(name="label_format")
def validate_label_format(ctx: CheckContext) -> CheckResult:
    """校验所有标注文件的 YOLO 格式合法性."""
    snap = ctx.snapshot

    # 收集所有 split 的标注文件列表
    all_labels: list = []
    for split_name in snap.labels_per_split:
        all_labels.extend(snap.labels_per_split[split_name])

    if not all_labels:
        return CheckResult(
            name="label_format",
            severity=CheckSeverity.INFO,
            summary="数据集无标注文件可供检查",
            details={"total_labels": 0},
        )

    # 逐文件检查
    total_labels = 0
    total_lines = 0
    bad_files_count = 0
    bad_lines_total = 0
    merged_error_counts: Dict[str, int] = {
        WRONG_COLUMN_COUNT: 0,
        NON_NUMERIC: 0,
        CLASS_NOT_INTEGER: 0,
        COORD_OUT_OF_RANGE: 0,
        DIMENSION_ZERO_OR_NEG: 0,
        DIMENSION_EXCEEDS_ONE: 0,
        FILE_READ_ERROR: 0,
    }
    merged_bad_examples: List[Dict[str, Any]] = []

    for label_path in all_labels:
        total_labels += 1
        has_error, file_lines, file_bad, file_errors, file_examples = _validate_one_label(label_path)
        total_lines += file_lines
        if has_error:
            bad_files_count += 1
        bad_lines_total += file_bad
        for k in merged_error_counts:
            merged_error_counts[k] += file_errors.get(k, 0)
        # 追加 bad_examples 直到 DETAILS_PREVIEW_LIMIT
        remaining = DETAILS_PREVIEW_LIMIT - len(merged_bad_examples)
        if remaining > 0:
            merged_bad_examples.extend(file_examples[:remaining])

    # 分级
    bad_files_ratio = bad_files_count / total_labels

    if bad_files_ratio == 0.0:
        severity = CheckSeverity.PASS
        summary = f"全部 {total_labels} 个标注文件格式合法 (共 {total_lines} 行)"
    elif bad_files_ratio <= LABEL_FORMAT_WARN_RATIO:
        severity = CheckSeverity.INFO
        summary = (f"{total_labels} 个文件中 {bad_files_count} 个有格式错误 "
                   f"({bad_files_ratio:.2%}), 共 {bad_lines_total} 行问题")
    elif bad_files_ratio <= LABEL_FORMAT_ERROR_RATIO:
        severity = CheckSeverity.WARNING
        summary = (f"{total_labels} 个文件中 {bad_files_count} 个有格式错误 "
                   f"({bad_files_ratio:.2%}), 共 {bad_lines_total} 行问题")
    else:
        severity = CheckSeverity.ERROR
        summary = (f"{total_labels} 个文件中 {bad_files_count} 个有格式错误 "
                   f"({bad_files_ratio:.2%}), 共 {bad_lines_total} 行问题")

    return CheckResult(
        name="label_format",
        severity=severity,
        summary=summary,
        details={
            "total_labels":     total_labels,
            "total_lines":      total_lines,
            "bad_files_count":  bad_files_count,
            "bad_files_ratio":  bad_files_ratio,
            "bad_lines_count":  bad_lines_total,
            "error_counts":     merged_error_counts,
            "bad_examples":     merged_bad_examples,
        },
    )
```

- [ ] **Step 2: Verify import works**

```bash
cd "D:/Demo/python/ODplatform" && "D:/conda/2024/envs/odplat-gpu/python.exe" -c "from odp_platform.data_validation.checks.label_format import validate_label_format; print('import OK')"
```

Expected output: `import OK`

- [ ] **Step 3: Verify check is auto-discovered**

```bash
cd "D:/Demo/python/ODplatform" && "D:/conda/2024/envs/odplat-gpu/python.exe" -c "from odp_platform.data_validation import list_check_names; print(list_check_names())"
```

Expected output: `['pair_existence', 'yaml_schema', 'label_format']`

- [ ] **Step 4: Run existing test to confirm new check integrates without breaking**

```bash
cd "D:/Demo/python/ODplatform" && "D:/conda/2024/envs/odplat-gpu/python.exe" apps/platform/tests/check_test.py
```

Expected: 3 个 check 都运行通过（label_format 应输出 PASS 或 INFO/WARNING/ERROR）

- [ ] **Step 5: Commit**

```bash
cd "D:/Demo/python/ODplatform" && git add apps/platform/src/odp_platform/data_validation/checks/label_format.py && git commit -m "feat: add label_format check — validate YOLO label file content"
```

---

### Task 3: Smoke test with sample data

- [ ] **Step 1: Write a quick smoke test script**

创建临时测试脚本 `apps/platform/tests/smoke_label_format.py`：

```python
"""label_format 冒烟测试 — 用真实数据集跑一次看结果"""
from pathlib import Path
from odp_platform.common.paths import dataset_yaml_path, LOGGING_DIR
from odp_platform.common.logging_utils import get_logger
from odp_platform.data_validation.snapshot import build_snapshot
from odp_platform.data_validation import CheckContext, run_all_checks, list_check_names

# 初始化日志
get_logger(base_path=LOGGING_DIR, log_type="smoke_label_format", temp_log=True)

# 确保 check 已注册
print("已注册 check:", list_check_names())

# 构建 snapshot + context
yaml_path = dataset_yaml_path("plantdoc")
snap = build_snapshot(yaml_path, task_type="detect")
ctx = CheckContext(yaml_path=yaml_path, snapshot=snap)

# 只跑 label_format
for r in run_all_checks(ctx):
    if r.name == "label_format":
        print(f"\n  {r.severity:7s} {r.name:20s} {r.summary}")
        print(f"  details keys: {list(r.details.keys())}")
        if r.details.get("error_counts"):
            print(f"  error_counts: {r.details['error_counts']}")
        if r.details.get("bad_examples"):
            print(f"  bad_examples ({len(r.details['bad_examples'])} 条):")
            for ex in r.details["bad_examples"][:3]:
                print(f"    - {ex}")
```

- [ ] **Step 2: Run smoke test**

```bash
cd "D:/Demo/python/ODplatform" && "D:/conda/2024/envs/odplat-gpu/python.exe" apps/platform/tests/smoke_label_format.py
```

Expected: label_format check 输出 PASS（plantdoc 数据集标注格式应合法）

- [ ] **Step 3: Clean up smoke test (不提交)**

```bash
rm apps/platform/tests/smoke_label_format.py
```
