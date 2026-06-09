#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :random_split.py
# @Time      :2026/6/9 15:28:55
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :L0：纯随机划分策略
"""L0: 纯随机划分策略 (7.2 版逻辑搬家, 算法零改动)。"""
from __future__ import annotations

import logging

from sklearn.model_selection import train_test_split  # 可以不用他，我们自己写划分逻辑。会好些

from odp_platform.common.constants import RATE_EPSILON, SplitStrategy
from odp_platform.data_pipeline.split.manifest import PairList, SplitManifest
from odp_platform.data_pipeline.split.strategy_registry import SplitOptions, register_strategy

logger = logging.getLogger(__name__)


@register_strategy(SplitStrategy.RANDOM, requires_labels=False)
def random_split(pairs: PairList, options: SplitOptions) -> SplitManifest:
    """纯随机划成 train/val/test。"""
    train_rate, val_rate, random_state = options.train_rate, options.val_rate, options.random_state
    test_rate = 1.0 - train_rate - val_rate
    if not (0 <= train_rate <= 1 and 0 <= val_rate <= 1 and 0 <= test_rate <= 1):
        raise ValueError(f"比例越界: train={train_rate}, val={val_rate}, test={test_rate:.4f}")

    manifest = SplitManifest(
        train_rate=train_rate, val_rate=val_rate, test_rate=test_rate,
        random_state=random_state, strategy=SplitStrategy.RANDOM,
    )
    n = len(pairs)
    if n == 0:
        return manifest
    if n < 3:
        logger.warning(f"random_split: 样本数 {n} < 3, 全归 train")
        manifest.train = list(pairs); return manifest
    if train_rate >= 1.0 - RATE_EPSILON:
        manifest.train = list(pairs); return manifest

    images = [p[0] for p in pairs]; labels = [p[1] for p in pairs]
    train_i, temp_i, train_l, temp_l = train_test_split(
        images, labels, train_size=train_rate, random_state=random_state,
    )
    manifest.train = list(zip(train_i, train_l))
    if not temp_i:
        return manifest

    remaining = val_rate + test_rate
    if remaining < RATE_EPSILON or len(temp_i) < 2:
        # 若用户未请求 val 集, 剩余数据归 test; 否则归 val
        if val_rate < RATE_EPSILON:
            manifest.test = list(zip(temp_i, temp_l))
        else:
            manifest.val = list(zip(temp_i, temp_l))
        return manifest
    if test_rate < RATE_EPSILON:
        manifest.val = list(zip(temp_i, temp_l)); return manifest
    if val_rate < RATE_EPSILON:
        manifest.test = list(zip(temp_i, temp_l)); return manifest

    val_size = val_rate / remaining
    val_i, test_i, val_l, test_l = train_test_split(
        temp_i, temp_l, train_size=val_size, random_state=random_state,
    )
    manifest.val = list(zip(val_i, val_l))
    manifest.test = list(zip(test_i, test_l))
    return manifest


