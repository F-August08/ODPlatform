#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :registry.py
# @Time      :2026/6/9 11:32:51
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""data_pipeline 注册表 + 统一参数包 + 能力声明。

设计要点:
    - 一个 dict (_REGISTRY) 存"format -> ConverterEntry"映射
    - @register 装饰器在 converter 文件被 import 时自动登记
    - ConvertOptions 是所有 converter 共用的参数包
    - ConverterEntry 同时携带"实现函数 + 能力声明"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from odp_platform.common.constants import AnnotationFormat, Task

logger = logging.getLogger(__name__)


# ============================================================
# 统一参数包: 所有 converter 函数签名一致
# ============================================================
@dataclass
class ConvertOptions:
    """所有 converter 共用的参数包。

    每个 converter 按需取用——不需要的字段忽略即可。
    新增字段时, 老 converter 自动兼容(因为不读它就行)。
    """
    task: str = Task.DETECT
    """任务类型: detect / segment / ..."""

    classes: Optional[List[str]] = None
    """类别白名单。
    - 对 pascal_voc / coco: 一般为 None, converter 自己探测
    - 对 yolo: 必须传, 因为 yolo 格式不含类别名信息
    """

    coco_cls91to80: bool = False
    """COCO 专属: 是否做 91 类 → 80 类映射"""


# ============================================================
# 注册表条目
# ============================================================
ConverterFunc = Callable[[Path, Path, ConvertOptions], List[str]]
"""converter 函数签名:
    (input_dir, output_labels_dir, options) -> List[str](类别名)
"""


@dataclass(frozen=True)
class ConverterEntry:
    """注册表里一条记录: 函数 + 它的能力声明。"""
    func: ConverterFunc
    supported_tasks: Tuple[str, ...]

    def supports(self, task: str) -> bool:
        return task in self.supported_tasks


# ============================================================
# 注册表本体 (模块级单例)
# ============================================================
_REGISTRY: Dict[str, ConverterEntry] = {}


def register(
    format_name: str,
    supported_tasks: Tuple[str, ...] = (Task.DETECT,),
) -> Callable[[ConverterFunc], ConverterFunc]:
    """装饰器: 把一个 converter 函数注册到 _REGISTRY。

    Usage:
        @register("pascal_voc", supported_tasks=(Task.DETECT,))
        def convert_voc(input_dir, output_labels_dir, options):
            ...
    """
    def decorator(func: ConverterFunc) -> ConverterFunc:
        if format_name in _REGISTRY:
            logger.warning(f"格式 {format_name} 被重复注册, 后者覆盖前者")
        _REGISTRY[format_name] = ConverterEntry(
            func=func,
            supported_tasks=tuple(supported_tasks),
        )
        logger.debug(
            f"注册 converter: format={format_name}, "
            f"tasks={supported_tasks}"
        )
        return func
    return decorator


# ============================================================
# 查询 API (供 service.py / CLI / 测试使用)
# ============================================================
def get_converter(format_name: str) -> ConverterEntry:
    """按 format 名取出 ConverterEntry。

    Raises:
        ValueError: 未注册的格式
    """
    _lazy_init()
    if format_name not in _REGISTRY:
        raise ValueError(
            f"未注册的格式: {format_name!r}。"
            f"已注册: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[format_name]


def list_capabilities() -> Dict[str, Tuple[str, ...]]:
    """返回当前所有已注册格式 → 支持的 task 列表。
    用于 CLI --help 显示能力矩阵。"""
    _lazy_init()
    return {fmt: entry.supported_tasks for fmt, entry in _REGISTRY.items()}


# ============================================================
# 延迟初始化: 解决循环 import
# ============================================================
_LAZY_INITIALIZED = False


def _lazy_init() -> None:
    """触发 core/*.py 被 import, 使 @register 装饰器执行注册。

    为什么需要延迟初始化:
        如果 registry.py 顶部直接 `import data_pipeline.core.pascal_voc`,
        而 pascal_voc.py 里又 `from data_pipeline.registry import register`,
        就形成循环 import。把 import 推迟到首次查询时, 循环就解开了。
    """
    global _LAZY_INITIALIZED
    if _LAZY_INITIALIZED:
        return
    _LAZY_INITIALIZED = True

    # 在这里 import 所有 converter 实现文件——它们的 @register 装饰器
    # 在 import 时执行, 自动登记到 _REGISTRY
    # from odp_platform.data_pipeline.core import pascal_voc  # noqa: F401
    # from odp_platform.data_pipeline.core import coco        # noqa: F401
    # from odp_platform.data_pipeline.core import yolo        # noqa: F401
