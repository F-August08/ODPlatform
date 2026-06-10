#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :service.py
# @Time      :2026/6/10 10:31:05
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
# apps/platform/src/odp_platform/data_validation/service.py
"""data_validation 调度层 — run_all_checks。

聚合模式核心承诺: 任何 check 抛异常都不能阻断其他 check。
这条承诺通过 _safe_run_one 里的 try/except Exception 兑现 —— 整个 D4 子系统
里仅此一处用到 Exception 这种宽泛的捕获, 因为这里是"开闭原则下的扩展点"
(谁都能加 check), 调度层无法预知 check 会抛什么。

其他地方应该用具体的 except OSError / except yaml.YAMLError 等。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from odp_platform.common.performance_utils import time_it
from odp_platform.common.paths import validation_run_dir
from odp_platform.data_validation.registry import (
    CheckContext, CheckEntry, CheckResult, CheckSeverity, get_all_checks,
)
from odp_platform.data_validation.report import ValidationReport
from odp_platform.data_validation.snapshot import build_snapshot

logger = logging.getLogger(__name__)


@time_it(name="run_all_checks",logger_instance=logger, iterations=1)
def run_all_checks(ctx: CheckContext) -> List[CheckResult]:
    """跑全部注册的 check, 收集结果。

    聚合模式承诺:
        任何 check 自身抛异常都被本函数接住, 包装成 ERROR 级 CheckResult,
        不阻断其他 check。 这是 D4 跟 D3 (互斥模式) 最大的区别 —— D3 service.convert
        失败立刻抛, D4 service.run_all_checks 失败也继续。

    Returns:
        List[CheckResult] — 按 check 注册顺序, 一条不漏
    """
    entries = get_all_checks()  # 拿到所有注册的检查
    logger.info(f"开始执行 {len(entries)} 个 check")

    results: List[CheckResult] = []
    for entry in entries:
        result = _safe_run_one(entry, ctx)
        _log_check_result(result)
        results.append(result)

    _log_summary(results)
    return results


def _safe_run_one(entry: CheckEntry, ctx: CheckContext) -> CheckResult:
    """跑单个 check, 异常包装成 ERROR — 聚合模式承诺的兑现处。

    设计:
        - try/except Exception 是【唯一】合理使用宽泛捕获的地方。
        理由: check 是开闭原则下的扩展点, 谁都能加新 check, 调度层无法预知
        它会抛什么(KeyError / TypeError / 自定义异常 / ...)。 接住一切,
        包装成 ERROR 级 CheckResult, 让其他 check 继续。

        - exc_info=True: 把完整 traceback 写到日志, 方便事后排查 — 这条信息
        会出现在 CheckResult.summary 里(避免污染用户看到的简短摘要),
        但保留在日志文件里, 调试时 grep 一下就有。
    """
    try:
        return entry.func(ctx)
    except Exception as e:
        logger.exception(f"check '{entry.name}' 抛异常, 已捕获为 ERROR 级结果")
        return CheckResult(
            name=entry.name,
            severity=CheckSeverity.ERROR,
            summary=f"check 内部异常: {type(e).__name__}: {e}",
            details={
                "exception_type": type(e).__name__,
                "exception_msg":  str(e),
            },
        )


def _log_check_result(r: CheckResult) -> None:
    """单个 check 跑完即时打一条日志, 让用户看到进度。

    Severity → log level 映射:
        ERROR   → logger.error
        WARNING → logger.warning
        INFO    → logger.info
        PASS    → logger.debug   (默认不显示, -v 才看)

    为什么 PASS 走 DEBUG:
        PASS 不是"事件", 是"非事件" — 健康数据集每次跑 4 行 [PASS] 刷屏,
        噪声盖过信号。 日志只记 WARN/ERROR/INFO 这种"有变化"的事件,
        PASS 信息走 ValidationReport 的最终摘要 (阶段 8 的 render.py),
        集中展示。
    """
    log_method = {
        CheckSeverity.ERROR:   logger.error,
        CheckSeverity.WARNING: logger.warning,
        CheckSeverity.INFO:    logger.info,
        CheckSeverity.PASS:    logger.debug,
    }.get(r.severity, logger.info)

    log_method(f"[{r.severity:7s}] {r.name}: {r.summary}")


def _log_summary(results: List[CheckResult]) -> None:
    """所有 check 跑完后, 打一行总览。"""
    counts = {}
    for r in results:
        counts[r.severity] = counts.get(r.severity, 0) + 1
    parts = [f"{n} {s}" for s, n in counts.items()]
    logger.info(f"check 执行完毕: {' / '.join(parts)}")


# ============================================================
# 端到端便捷入口 — validate_dataset
# ============================================================

def validate_dataset(
    yaml_path: Path,
    task_type: Optional[str] = None,
    write_report: bool = True,
) -> ValidationReport:
    """数据集验证的端到端入口 — 构建快照 → 跑全部 check → 组装报告。

    这是 data_validation 子系统的顶级 API, 供 CLI (validate_data.py) 和
    程序化调用使用。

    Args:
        yaml_path:    数据集 yaml 文件路径
        task_type:    任务类型 ("detect" / "segment"), None = 自动读取
        write_report: 是否将 JSON 报告落盘到 runs/data_validation/<run_id>/

    Returns:
        ValidationReport — 含 run_id / snapshot / results / overall_severity 等
    """
    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%d_%H%M%S")

    # 1. 构建快照
    snap = build_snapshot(yaml_path, task_type=task_type)

    # 2. 跑全部 check
    ctx = CheckContext(yaml_path=yaml_path, snapshot=snap)
    t0 = time.perf_counter()
    results = run_all_checks(ctx)
    duration = time.perf_counter() - t0

    # 3. 组装报告
    run_dir = validation_run_dir(run_id) if write_report else None
    report = ValidationReport(
        run_id=run_id,
        yaml_path=yaml_path,
        snapshot=snap,
        results=results,
        duration_seconds=duration,
        started_at_iso=started_at.isoformat(),
        run_dir=run_dir,
    )

    # 4. 可选: 写 JSON 报告
    if write_report and run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / "report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"JSON 报告已写入: {report_path}")

    return report