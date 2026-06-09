#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :coco.py
# @Time      :2026/6/9 11:58:50
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""COCO → YOLO converter (detect / segment), 包 ultralytics 实现, tempfile 中转。"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import List

from odp_platform.common.constants import AnnotationFormat, Task
from odp_platform.data_pipeline.registry import ConvertOptions, register

logger = logging.getLogger(__name__)


@register(AnnotationFormat.COCO, supported_tasks=(Task.DETECT, Task.SEGMENT))
def convert_coco(
    input_dir: Path,
    output_labels_dir: Path,
    options: ConvertOptions,
) -> List[str]:
    """把 input_dir 下的 COCO JSON 转 YOLO txt。

    Returns:
        类别名列表 (顺序与 COCO categories 的 'id' 升序一致)
    """
    # 第三方重依赖延迟 import
    from ultralytics.data.converter import convert_coco as _ul_convert_coco

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        raise FileNotFoundError(f"在 {input_dir} 下未找到 COCO JSON")
    if len(json_files) > 1:
        logger.warning(f"找到多个 JSON, 仅使用第一个: {json_files[0].name}")
    coco_json = json_files[0]

    classes = _read_classes(coco_json)
    logger.info(f"COCO 类别 {len(classes)} 种")

    output_labels_dir.mkdir(parents=True, exist_ok=True)
    tmp_root = Path(tempfile.mkdtemp(prefix="odp_coco_"))   # ★ 中转
    try:
        _ul_convert_coco(
            labels_dir=str(input_dir),
            save_dir=str(tmp_root),
            use_segments=(options.task == Task.SEGMENT),
            cls91to80=options.coco_cls91to80,
        )
        n = _flatten_txts(tmp_root, output_labels_dir)
        logger.info(f"COCO 转换完成: {n} 个 yolo txt")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)         # ★ 总是清理

    return classes


def _read_classes(coco_json: Path) -> List[str]:
    data = json.loads(coco_json.read_text(encoding="utf-8"))
    cats = sorted(data.get("categories", []), key=lambda c: c["id"])
    return [c["name"] for c in cats]


def _flatten_txts(src_root: Path, dst_dir: Path) -> int:
    n = 0
    for txt in src_root.rglob("*.txt"):
        shutil.copy2(txt, dst_dir / txt.name)
        n += 1
    return n