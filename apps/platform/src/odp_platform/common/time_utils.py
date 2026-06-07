#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  : time_utils.py
# @Author    : 雨霓同学 (ODPlatform team)
# @Project   : ODPlatform
# @Function  : 计时工具集——装饰器、上下文管理器，用于性能分析与耗时统计
#
# 设计哲学:
#   - time_it: 装饰器, 对函数做 N 次迭代取统计 (均值/最值/标准差)
#   - Timer:   上下文管理器, 对代码块做单次计时
#   - 输出格式遵循项目统一的 LINE_WIDTH = 80 排版规范

import time
import functools
import logging
import statistics
from typing import Callable, Optional, Any, List

logger = logging.getLogger(__name__)

LINE_WIDTH: int = 80


def time_it(
    iterations: int = 1,
    name: Optional[str] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> Callable:
    """装饰器：对函数进行指定次数的计时并输出统计信息。

    设计要点:
        - 多次运行取统计 (均值 / 最小值 / 最大值 / 标准差)
        - 通过 ``functools.wraps`` 保留原函数的 __name__ / __doc__ 等元数据
        - 通过 ``__wrapped__`` 属性可访问未装饰的原函数,
          供 profile_init.py 等外部脚本做独立计时

    Args:
        iterations: 运行次数, 默认 1
        name: 操作名称, 默认使用被装饰函数的 ``__name__``
        logger_instance: 指定 logger 实例, 默认使用本模块 logger

    Returns:
        装饰后的函数 (返回值与原函数一致, 取最后一次迭代的结果)

    Usage::

        >>> from odp_platform.common.time_utils import time_it
        >>> logger = logging.getLogger(__name__)
        >>>
        >>> @time_it(iterations=10, name='项目初始化', logger_instance=logger)
        ... def initialize_project():
        ...     ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log = logger_instance or logger
            display_name = name or func.__name__

            log.info("")
            log.info(f"[性能分析] {display_name}".center(LINE_WIDTH, "="))
            log.info(f"运行次数: {iterations}")

            times: List[float] = []
            result = None

            for i in range(iterations):
                start = time.perf_counter()
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                times.append(elapsed)
                log.info(
                    f"  第 {i+1}/{iterations} 次: "
                    f"{elapsed:.4f}s ({elapsed*1000:.2f}ms)"
                )

            # ---- 统计汇总 ----
            if iterations == 1:
                log.info(f"  耗时: {times[0]:.4f}s ({times[0]*1000:.2f}ms)")
            else:
                mean_t = statistics.mean(times)
                min_t = min(times)
                max_t = max(times)
                stdev_t = statistics.stdev(times)

                log.info(f"  {'─' * 40}")
                log.info(f"  平均耗时:  {mean_t:.4f}s ({mean_t*1000:.2f}ms)")
                log.info(f"  最小耗时:  {min_t:.4f}s ({min_t*1000:.2f}ms)")
                log.info(f"  最大耗时:  {max_t:.4f}s ({max_t*1000:.2f}ms)")
                log.info(f"  标准差:    {stdev_t:.4f}s")

            log.info("=" * LINE_WIDTH)
            return result

        return wrapper

    return decorator


class Timer:
    """上下文管理器：对 ``with`` 代码块做单次计时。

    进入 ``with`` 时开始计时, 退出时自动输出耗时。

    Usage::

        >>> from odp_platform.common.time_utils import Timer
        >>> with Timer("创建目录", logger_instance=logger):
        ...     create_directories()
        ... # [创建目录] 耗时: 0.0123s (12.30ms)
    """

    def __init__(
        self,
        name: str = "操作",
        logger_instance: Optional[logging.Logger] = None,
    ) -> None:
        """初始化计时器。

        Args:
            name: 操作名称, 用于日志输出
            logger_instance: 指定 logger, 默认使用本模块 logger
        """
        self.name = name
        self.log = logger_instance or logger
        self._start: float = 0.0
        self.elapsed: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed = time.perf_counter() - self._start
        self.log.info(
            f"[{self.name}] 耗时: {self.elapsed:.4f}s "
            f"({self.elapsed*1000:.2f}ms)"
        )


if __name__ == "__main__":
    # ---- 模块自测 ----
    from odp_platform.common.logging_utils import get_logger
    from odp_platform.common.paths import LOGGING_DIR

    # 装配日志
    get_logger(base_path=LOGGING_DIR, log_type="time_utils_test", temp_log=True)

    test_logger = logging.getLogger(__name__)

    # --- 测试 1: 装饰器 ---
    @time_it(iterations=3, name="自测函数", logger_instance=test_logger)
    def _dummy_work():
        time.sleep(0.01)

    _dummy_work()

    # --- 测试 2: 上下文管理器 ---
    with Timer("代码块计时", logger_instance=test_logger):
        time.sleep(0.02)
