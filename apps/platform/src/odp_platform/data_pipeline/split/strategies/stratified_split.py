#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :stratified_split.py
# @Time      :2026/6/9 15:31:25
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :主要类别分层划分策略-取每张图出现最多的类作为分成键，确保各类占比一致
"""L1: 主类别分层划分——取每张图出现最多的类作为分层键, 保证各类占比一致。"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, List

from sklearn.model_selection import train_test_split

from odp_platform.common.constants import RATE_EPSILON, SplitStrategy
from odp_platform.data_pipeline.split.manifest import PairList, SplitManifest
from odp_platform.data_pipeline.split.strategy_registry import SplitOptions, register_strategy

logger = logging.getLogger(__name__)

_EMPTY_KEY = "__empty__"   # 无标注图像的分层键


def _primary_class(class_names: List[str]) -> str:
    """分层键 = 出现次数最多的类别名。并列时取首次出现 (Counter 保留插入序, 跨运行稳定)。"""
    if not class_names:
        return _EMPTY_KEY
    return Counter(class_names).most_common(1)[0][0]


def _build_stratify_keys(pairs: PairList, labels_per_image: Dict[str, List[str]]) -> List[str]:
    """为每个 pair 算分层键 (顺序与 pairs 对齐)。"""
    return [_primary_class(labels_per_image.get(img.stem, [])) for img, _ in pairs]


def _stratify_feasible(keys: List[str]) -> bool:
    """分层是否可行: 每个分层键至少 2 个样本 (sklearn 硬性要求)。"""
    too_rare = [k for k, c in Counter(keys).items() if c < 2]
    if too_rare:
        logger.error(f"分层不可行: 以下分层键样本数 < 2: {too_rare}")
        return False
    return True


@register_strategy(SplitStrategy.STRATIFIED, requires_labels=True)
def stratified_split(pairs: PairList, options: SplitOptions) -> SplitManifest:
    """主类别分层划分。

    Raises:
        ValueError: 比例越界 / 没传 labels_per_image / 分层数学上不可行。
                    (不静默退回随机——尊重用户知情权)
    """
    train_rate, val_rate, random_state = options.train_rate, options.val_rate, options.random_state
    test_rate = 1.0 - train_rate - val_rate
    if not (0 <= train_rate <= 1 and 0 <= val_rate <= 1 and 0 <= test_rate <= 1):
        raise ValueError(f"比例越界: train={train_rate}, val={val_rate}, test={test_rate:.4f}")

    if options.labels_per_image is None:
        raise ValueError(
            "stratified 策略需要 labels_per_image (每张图的类别列表), 但收到 None。"
        )

    manifest = SplitManifest(
        train_rate=train_rate, val_rate=val_rate, test_rate=test_rate,
        random_state=random_state, strategy=SplitStrategy.STRATIFIED,
    )
    n = len(pairs)
    if n == 0:
        return manifest
    if n < 3:
        logger.warning(f"stratified_split: 样本数 {n} < 3, 全归 train")
        manifest.train = list(pairs); return manifest
    if train_rate >= 1.0 - RATE_EPSILON:
        manifest.train = list(pairs); return manifest

    keys = _build_stratify_keys(pairs, options.labels_per_image)
    if not _stratify_feasible(keys):
        raise ValueError(
            "数据集无法分层 (存在样本数 < 2 的类别)。"
            "可选: (a) 补充稀有类样本; (b) 改用 --split-strategy random。"
        )

    images = [p[0] for p in pairs]; labels = [p[1] for p in pairs]
    # 第一次切: train vs temp (带 stratify)
    train_i, temp_i, train_l, temp_l, _train_k, temp_k = train_test_split(
        images, labels, keys, train_size=train_rate,
        random_state=random_state, stratify=keys,
    )
    manifest.train = list(zip(train_i, train_l))
    if not temp_i:
        return manifest

    remaining = val_rate + test_rate
    if remaining < RATE_EPSILON or len(temp_i) < 2 or test_rate < RATE_EPSILON:
        # 若用户未请求 val 集, 剩余数据归 test; 否则归 val
        if val_rate < RATE_EPSILON:
            manifest.test = list(zip(temp_i, temp_l))
        else:
            manifest.val = list(zip(temp_i, temp_l))
        return manifest
    if val_rate < RATE_EPSILON:
        manifest.test = list(zip(temp_i, temp_l)); return manifest

    # 第二次切: temp -> val vs test (temp 子集若某类剩 1 个则局部退回随机, 并告警)
    val_size = val_rate / remaining
    if _stratify_feasible(temp_k):
        val_i, test_i, val_l, test_l = train_test_split(
            temp_i, temp_l, train_size=val_size,
            random_state=random_state, stratify=temp_k,
        )
    else:
        logger.warning("temp 子集无法二次分层, val/test 间退回随机切 (train 分层不受影响)。")
        val_i, test_i, val_l, test_l = train_test_split(
            temp_i, temp_l, train_size=val_size, random_state=random_state,
        )
    manifest.val = list(zip(val_i, val_l))
    manifest.test = list(zip(test_i, test_l))
    return manifest