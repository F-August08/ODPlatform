#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :strategy_registry.py
# @Time      :2026/6/9 15:18:49
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""split 子系统的划分策略注册表 + 统一参数包 (与 data_pipeline.registry 同构)。"""
from __future__ import annotations

import logging
import pkgutil
import importlib
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from odp_platform.common.constants import DEFAULT_RANDOM_STATE
from odp_platform.data_pipeline.split.manifest import PairList, SplitManifest

logger = logging.getLogger(__name__)


# ============================================================
# 统一参数包: 所有划分策略签名一致
# ============================================================
@dataclass
class SplitOptions:
    """所有划分策略共用的参数包。random 只读 rates/seed; stratified 还读
    labels_per_image; 未来 group 还读 group_per_image。"""
    train_rate: float = 0.8
    val_rate:   float = 0.1
    random_state: int = DEFAULT_RANDOM_STATE

    labels_per_image: Optional[Dict[str, List[str]]] = None
    """{image_stem: [类别名,...]}。对 random 一般为 None; 对 stratified 必传。
    用 None 不用 {}: None="没提供", {}="每张图都没类别", 两种语义不能混。"""

    group_per_image: Optional[Dict[str, str]] = None
    """{image_stem: group_id}。预留给未来 L2 group 策略。"""


# ============================================================
# 注册表条目: 函数 + 能力声明
# ============================================================
StrategyFunc = Callable[[PairList, SplitOptions], SplitManifest]


@dataclass(frozen=True)
class StrategyEntry:
    """注册表里一条记录: 实现函数 + 是否需要类别信息。"""
    func: StrategyFunc
    requires_labels: bool = False
    """该策略是否依赖 labels_per_image。调度层据此提前 fail-fast。"""


# ============================================================
# 注册表本体 (模块级单例)
# ============================================================
_STRATEGY_REGISTRY: Dict[str, StrategyEntry] = {}


def register_strategy(
    name: str, *, requires_labels: bool = False,
) -> Callable[[StrategyFunc], StrategyFunc]:
    """装饰器: 把一个划分策略注册到 _STRATEGY_REGISTRY。"""
    def decorator(func: StrategyFunc) -> StrategyFunc:
        if name in _STRATEGY_REGISTRY:
            logger.warning(f"划分策略 {name} 被重复注册, 后者覆盖前者")
        _STRATEGY_REGISTRY[name] = StrategyEntry(func=func, requires_labels=requires_labels)
        logger.debug(f"注册划分策略: {name} (requires_labels={requires_labels})")
        return func
    return decorator


def get_strategy(name: str) -> StrategyEntry:
    """按名取出 StrategyEntry。Raises: ValueError 未注册的策略。"""
    _lazy_init()
    if name not in _STRATEGY_REGISTRY:
        raise ValueError(
            f"未注册的划分策略: {name!r}。已注册: {sorted(_STRATEGY_REGISTRY.keys())}"
        )
    return _STRATEGY_REGISTRY[name]


def list_strategies() -> Tuple[str, ...]:
    """返回当前所有已注册策略名。"""
    _lazy_init()
    return tuple(sorted(_STRATEGY_REGISTRY.keys()))


# ============================================================
# 延迟初始化 (与 data_pipeline.registry 同款)
# ============================================================
_LAZY_INITIALIZED = False


def _lazy_init() -> None:
    global _LAZY_INITIALIZED
    if _LAZY_INITIALIZED:
        return

    from odp_platform.data_pipeline.split import strategies

    for module_info in pkgutil.iter_modules(strategies.__path__):
        # 跳过以 _ 开头的私有/工具模块 (如 _helpers.py)
        if module_info.name.startswith("_"):
            continue
        importlib.import_module(f"{strategies.__name__}.{module_info.name}")

    _LAZY_INITIALIZED = True   # ★ 必须放在 import 全部成功之后
