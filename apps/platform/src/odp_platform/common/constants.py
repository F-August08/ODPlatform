#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :constants.py
# @Time      :2026/6/9 10:57:59
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""
项目级共享常量-所有模块的共享词汇表
"""


from typing import Tuple

# 图像的扩展名
IMAGE_EXTENSIONS: Tuple[str, ...] = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")

#  标注的格式名称
class AnnotationFormat:
    """
    标注的格式名称
    """

    YOLO = "yolo"
    COCO = "coco"
    PASCAL_VOC = "pascal_voc"

    @classmethod
    def all(cls) -> Tuple[str, ...]:
        return cls.YOLO, cls.COCO, cls.PASCAL_VOC

class Task:
    """
    任务名称
    """
    DETECT = "detect"
    SEGMENT = "segment"

    @classmethod
    def all(cls) -> Tuple[str, ...]:
        return cls.DETECT, cls.SEGMENT

# 浮点划分相关
DEFAULT_RANDOM_STATE: int = 42

RATE_EPSILON: float = 1e-6


# ============================================================
# 数据集划分策略 (split/ 子系统 + CLI 共享)
# ============================================================
class SplitStrategy:
    """数据集划分策略名 (字符串常量, 供 @register_strategy 装饰器直接吃)。

    设计同 AnnotationFormat: 用类常量不用 Enum, 因为注册表装饰器吃字符串。
    """
    RANDOM     = "random"       # L0: 纯随机抽样 (默认)
    STRATIFIED = "stratified"   # L1: 主类别分层抽样 (类别不平衡时用)
    # 预留 (本文不实现, 加文件即可扩展):
    #   GROUP       = "group"             # L2: 分组划分 (防视频/批次泄漏)
    #   STRAT_GROUP = "stratified_group"  # L3: 分层 + 分组

    @classmethod
    def all(cls) -> Tuple[str, ...]:
        return (cls.RANDOM, cls.STRATIFIED)


DEFAULT_SPLIT_STRATEGY: str = SplitStrategy.RANDOM
"""默认划分策略。设为 RANDOM 是因为它不挑数据、零额外输入, 是主流场景的零成本默认。"""

# ============================================================
# 数据集覆盖率阈值 (orchestrator 使用)
# ============================================================
COVERAGE_HARD_THRESHOLD: float = 0.5
"""图像-标注覆盖率硬阈值: 低于此值直接 fail-fast。"""

COVERAGE_SOFT_THRESHOLD: float = 0.9
"""图像-标注覆盖率软阈值: 低于此值仅警告。"""