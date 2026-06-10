#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :check_test.py
# @Time      :2026/6/10 10:40:21
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :数据验证模块集成测试 — 使用 ValidationReport + render_to_logger 输出完整报告
"""data_validation 集成测试。

跑全部已注册 check, 通过 ValidationReport 收集结果, 用 render_to_logger
输出规范的三段式 YOLO 数据集验证报告。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from odp_platform.common.paths import LOGGING_DIR, dataset_yaml_path
from odp_platform.common.logging_utils import get_logger
from odp_platform.data_validation import (
    CheckContext,
    ValidationReport,
    build_snapshot,
    list_check_names,
    render_to_logger,
    run_all_checks,
)

# ── 日志初始化 ──
logger = get_logger(
    base_path=LOGGING_DIR,
    log_type="data_validate",
    temp_log=False,
)

# ── 主流程 ──
def main() -> int:
    yaml_path = dataset_yaml_path("plantdoc")

    logger.info(f"已注册 check: {list_check_names()}")

    # 1. 构建快照
    started_at = datetime.now(timezone.utc)
    snap = build_snapshot(yaml_path, task_type="detect")

    # 2. 跑全部 check
    ctx = CheckContext(yaml_path=yaml_path, snapshot=snap)
    t0 = time.perf_counter()
    results = run_all_checks(ctx)
    duration = time.perf_counter() - t0

    # 3. 组装报告
    run_id = started_at.strftime("%Y%m%d_%H%M%S")
    report = ValidationReport(
        run_id=run_id,
        yaml_path=yaml_path,
        snapshot=snap,
        results=results,
        duration_seconds=duration,
        started_at_iso=started_at.isoformat(),
    )

    # 4. 渲染输出
    render_to_logger(report, logger)

    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
