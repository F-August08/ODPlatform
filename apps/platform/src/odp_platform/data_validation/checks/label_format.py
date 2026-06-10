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
