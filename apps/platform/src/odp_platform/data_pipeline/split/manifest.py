#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :mainfest.py
# @Time      :2026/6/9 14:21:09
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :划分结果都数据载体

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

# 类型别名：一对样本 = (image_path, label_path)
Pair = Tuple[Path, Path]
PairList = List[Pair]

# 划分结果定义
@dataclass
class SplitManifest:
    """划分结果定义"""
    train: PairList = field(default_factory=list)
    val: PairList = field(default_factory=list)
    test: PairList = field(default_factory=list)

    train_rate: float = 0.0
    val_rate: float = 0.0
    test_rate: float = 0.0
    random_state: int = 0
    strategy: str = "random"  # 记录用那种划分厕所

    def summary(self) -> dict:
        return {
            "train": len(self.train),
            "val": len(self.val),
            "test": len(self.test),
            "total": len(self.train) + len(self.val) + len(self.test),
        }







