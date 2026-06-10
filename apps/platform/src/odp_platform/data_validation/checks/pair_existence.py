#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :pair_existence.py
# @Time      :2026/6/10 14:16:01
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
from __future__ import annotations
from typing import Any, Dict, List

from odp_platform.common.constants import (
    PAIR_MISSING_ERROR_RATIO,
    PAIR_MISSING_WARN_RATIO
)
from odp_platform.data_validation.registry import (check, CheckContext, CheckResult, CheckSeverity)

DETAILS_PREVIEW_LIMIT: int = 10

@check(name="pair_existence")
def validate_pair_existence(ctx: CheckContext) -> CheckResult:
    snap = ctx.snapshot
    if not snap.images_per_split:
        return CheckResult(
            name="pair_existence",
            severity=CheckSeverity.INFO,
            summary="数据集无图像，无任何split可供检查",
            details={
                "reason": "empty_snapshot",
            },
        )

    # 收集每个split的孤儿图像
    orphan_per_split: Dict[str, List[str]] = {}
    total_images = 0
    total_missing = 0
    for split, images in snap.images_per_split.items():
        labels = snap.labels_per_split.get(split, ())
        missing_in_split: List[str] = []
        for img, lbl in zip(images, labels):
            total_images += 1
            if not lbl.exists():
                total_missing += 1
                missing_in_split.append(str(img))
        if missing_in_split:
            orphan_per_split[split] = missing_in_split

    missing_ratio = total_missing / max(total_images,1)

    # 按比例进行分级
    if missing_ratio == 0:
        severity = CheckSeverity.PASS
        summary = f"所有图像共计：{total_images} 张都有对应的标注文件,没有缺失"
    elif missing_ratio >= PAIR_MISSING_ERROR_RATIO:
        severity = CheckSeverity.ERROR
        summary = f"所有图像共计：{total_images} 张，有 {total_missing} 张没有对应的标注文件, 缺失比例为 {missing_ratio:.2%}"
    elif missing_ratio >= PAIR_MISSING_WARN_RATIO:
        severity = CheckSeverity.WARNING
        summary = f"所有图像共计：{total_images} 张，有 {total_missing} 张没有对应的标注文件, 缺失比例为 {missing_ratio:.2%}"
    else:
        severity = CheckSeverity.INFO
        summary = f"所有图像共计：{total_images} 张，有 {total_missing} 张没有对应的标注文件, 缺失比例为 {missing_ratio:.2%}"

    # 构造details
    details: Dict[str, Any] = {
        "total_images": total_images,
        "total_missing": total_missing,
        "missing_ratio": missing_ratio,
        "thresholds": {
            "error_at": PAIR_MISSING_ERROR_RATIO,
            "warn_at": PAIR_MISSING_WARN_RATIO,
        },
        "missing_per_split": {
            split: len(orphans) for split, orphans in orphan_per_split.items()
        }
        }

    # 详细清单
    if orphan_per_split:
        details["missing_examples"] = {
            split: orphans[:DETAILS_PREVIEW_LIMIT] for split, orphans in orphan_per_split.items()
        }
    return CheckResult(
        name="pair_existence",
        severity=severity,
        summary=summary,
        details=details,
    )
