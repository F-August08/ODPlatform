#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :transform_data.py
# @Time      :2026/6/9 15:44:45
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
"""odp-transform: 原始数据集 -> YOLO格式 + 划分 + dataset yaml。"""
from __future__ import annotations

import argparse
import logging
import sys

from odp_platform.common.constants import (
    AnnotationFormat, DEFAULT_RANDOM_STATE, DEFAULT_SPLIT_STRATEGY,
    SplitStrategy, Task,
)
from odp_platform.common.paths import META_LOGGING_DIR
from odp_platform.common.logging_utils import get_logger
from odp_platform.data_pipeline.orchestrator import DatasetPipeline

logger = logging.getLogger(__name__)
get_logger(
    base_path = META_LOGGING_DIR,   # v4: 写到 .odp-meta/logs/, 不会被 reset 清理
    log_type="transform_data",
    temp_log=False,
)

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="odp-transform",
        description="把 data/raw/<dataset>/ 转成 YOLO 格式并划分, 生成 dataset yaml。",
    )
    p.add_argument("--dataset", required=True, help="数据集名 (= data/raw/ 下子目录名)")
    p.add_argument("--format", required=True, choices=list(AnnotationFormat.all()),
                help="原始标注格式")
    p.add_argument("--task", default=Task.DETECT, choices=list(Task.all()))
    p.add_argument("--train-rate", type=float, default=0.8)
    p.add_argument("--val-rate", type=float, default=0.1)
    p.add_argument("--random-state", type=int, default=DEFAULT_RANDOM_STATE)
    p.add_argument(
        "--split-strategy", default=DEFAULT_SPLIT_STRATEGY,
        choices=list(SplitStrategy.all()),
        help="划分策略: random (纯随机, 默认) / stratified (主类别分层, 类别不平衡时用)",
    )
    p.add_argument(
        "--classes", nargs="*", default=None,
        help="类别名列表, 空格分隔。yolo 格式必填 (如 --classes person car dog)。"
             "pascal_voc / coco 可省略, 会自动从标注中探测。"
             "如果 data/raw/<dataset>/classes.txt 存在, 也会自动读取。",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = DatasetPipeline(
            dataset_name=args.dataset,
            annotation_format=args.format,
            task=args.task,
            train_rate=args.train_rate,
            val_rate=args.val_rate,
            random_state=args.random_state,
            split_strategy=args.split_strategy,
            classes=args.classes,
        ).run()
    except FileNotFoundError as e:
        logger.error(f"数据缺失: {e}")
        return 2
    except ValueError as e:
        logger.error(f"参数/数据非法: {e}")
        return 3
    except Exception as e:                       # 兜底, 不向用户抛 traceback
        logger.exception(f"未预期错误: {e}")
        return 1

    logger.info(f"完成! 划分计数: {result['counts']}, yaml: {result['yaml']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())