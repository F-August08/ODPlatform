#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :__init__.py.py
# @Time      :2026/6/10 09:25:36
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :data_validation 公开 API
from odp_platform.data_validation.registry import (
    CheckContext,
    check,
    CheckResult,
    CheckSeverity,
    get_check,
    get_all_checks,
    list_check_names,
)

from odp_platform.data_validation.service import run_all_checks
from odp_platform.data_validation.snapshot import build_snapshot, DatasetSnapshot, SplitStats
from odp_platform.data_validation.report import ValidationReport
from odp_platform.data_validation.render import render_to_logger

__all__ = [
    # -- registry (数据契约 + 注册表) --
    "CheckContext",
    "check",
    "CheckResult",
    "CheckSeverity",
    "get_check",
    "get_all_checks",
    "list_check_names",
    # -- service (调度层) --
    "run_all_checks",
    # -- snapshot (数据载体) --
    "build_snapshot",
    "DatasetSnapshot",
    "SplitStats",
    # -- report (报告产出) --
    "ValidationReport",
    # -- render (展示层) --
    "render_to_logger",
]