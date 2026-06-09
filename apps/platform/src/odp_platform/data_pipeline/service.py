#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :service.py.py
# @Time      :2026/6/9 11:29:11
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :

from __future__  import annotations
from pathlib import Path
from typing import List

from odp_platform.data_pipeline.registry import (ConvertOptions, get_converter)

def convert_data_to_yolo(
        input_dir: Path,
        output_labels_dir: Path,
        annotation_format: str,
        options: ConvertOptions = ConvertOptions,
) -> List[str]:
    """把 input_dir 下的所有数据转换成 YOLO 格式。

    Args:
        input_dir: 输入目录, 存放原始数据
        output_labels_dir: 输出目录, 存放转换后的标签文件
        options: 转换选项

    Returns:
        转换成功的类名列表
    """
    entry = get_converter(annotation_format)
    if not entry.supports(options.task):
        raise ValueError(
            f"格式 {annotation_format} 不支持 task =  {options.task} 任务"
            f"当前支持的格式有：{entry.supported_tasks}"
        )
    return entry.func(input_dir, output_labels_dir, options)



