#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :check_test.py
# @Time      :2026/6/10 10:40:21
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
import logging
from pathlib import Path
from odp_platform.data_validation import CheckContext, run_all_checks, list_check_names
from odp_platform.common.paths import dataset_yaml_path
from odp_platform.data_validation.snapshot import build_snapshot
# 手动 import 一次 (因为 _placeholder 下划线开头, 自动 import 不抓它)

from odp_platform.common.logging_utils import get_logger
from odp_platform.common.paths import LOGGING_DIR
logger =  get_logger(
        base_path=LOGGING_DIR,
        log_type="data_validate",
        temp_log=False
    )



yaml_path = dataset_yaml_path('plantdoc')
snap = build_snapshot(yaml_path, task_type='detect')

#
# print(f'数据集: {yaml_path.name}')
# print(f'task:    {snap.task_type}')
# print(f'nc:      {snap.nc}')
# # print(f'classes: {snap.class_names}')
# print()
# for split, stat in snap.stats_per_split.items():
#     print(f'  {split:6s}: {stat.image_count:6d} 图  {stat.annotated_count:6d} 标注  {stat.total_instances:6d} 实例')
# print()
#
ctx = CheckContext(yaml_path=yaml_path, snapshot=snap)
for r in run_all_checks(ctx):
    print(f"   {r.severity:7s} {r.name:20s} {r.summary}")

