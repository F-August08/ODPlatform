#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :yolo.py
# @Time      :2026/6/9 12:00:42
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""YOLO → YOLO 直通 converter (接口等价): 把原始 txt 搬到 output_labels_dir。"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List

from odp_platform.common.constants import AnnotationFormat, Task
from odp_platform.data_pipeline.registry import ConvertOptions, register

logger = logging.getLogger(__name__)


@register(AnnotationFormat.YOLO, supported_tasks=(Task.DETECT, Task.SEGMENT))
def convert_yolo(
    input_dir: Path,
    output_labels_dir: Path,
    options: ConvertOptions,
) -> List[str]:
    """yolo 直通: 不解析内容, 只把 *.txt 搬到 output_labels_dir。

    Returns:
        类别名列表。yolo 格式不含类别名, 故必须由 options.classes 提供。
    """
    if not options.classes:
        raise ValueError(
            "yolo 格式不含类别名信息, 必须通过 options.classes 显式提供。"
        )

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(f"在 {input_dir} 下未找到任何 yolo txt")

    output_labels_dir.mkdir(parents=True, exist_ok=True)
    for txt in txt_files:
        dst = output_labels_dir / txt.name
        # 优先硬链接 (零拷贝, 省空间); 跨盘失败则退回复制
        try:
            if dst.exists():
                dst.unlink()
            os.link(txt, dst)
        except OSError:
            shutil.copy2(txt, dst)

    logger.info(f"YOLO 直通: {len(txt_files)} 个 txt 已就位, {len(options.classes)} 个类别")
    return list(options.classes)