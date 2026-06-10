from pathlib import Path
from typing import List
import logging

from odp_platform.common.paths import ROOT_DIR, get_dirs_to_initialize, LOGGING_DIR,RAW_DATA_DIR
from odp_platform.common.logging_utils import get_logger
from odp_platform.common.string_utils import format_table_row, format_table_separator
from odp_platform.common.system_utils import log_system_info
from odp_platform.common.performance_utils import time_it

LINE_WIDTH: int = 80

logger = logging.getLogger(__name__)
_snapshot_taken: bool = False

def _check_raw_data_status() -> List[str]:
    raw_status: List[str] = []
    rel_raw = RAW_DATA_DIR.relative_to(ROOT_DIR)

    if not RAW_DATA_DIR.exists():
        logger.warning(f"原始数据集根目录不存在:{RAW_DATA_DIR}\n"
                    f"请在该目录下创建以 [数据集名称] 命名的文件夹")
        raw_status.append(f"{rel_raw} 不存在 -> 请创建并放入数据集")
    elif not any(RAW_DATA_DIR.iterdir()):
        logger.warning(
            f"原始数据集根目录为空: {RAW_DATA_DIR}\n"
            f"预期结构:\n"
            f"  {rel_raw}/<数据集名>/\n"
            f"  ├── images/\n"
            f"  └── annotations/"
        )
        raw_status.append(f"{rel_raw} 内容为空, 请至少放入一个数据集")
    else:
        sub_dirs = [p for p in RAW_DATA_DIR.iterdir() if p.is_dir()]
        logger.info(f"原始数据集根目录就绪,检测到{len(sub_dirs)}个数据集文件夹")
        raw_status.append(f"{rel_raw}就绪,包含{len(sub_dirs)}个数据集")
        for sub in sorted(sub_dirs):
            raw_status.append(f"    * {sub.name}")
    return raw_status

@time_it(iterations=1, name='项目初始化', logger_instance=logger)
def initialize_project() -> None:
    get_logger(
        base_path=LOGGING_DIR,
        log_type="Init_project",
        temp_log=False

    )
    global _snapshot_taken
    if not _snapshot_taken:
        log_system_info(logger)
        _snapshot_taken = True
    logger.info(f"开始初始化项目核心目录".center(LINE_WIDTH, "="))
    logger.info(f"项目的根目录为: {ROOT_DIR}")

    created: List[Path] = []
    existed: List[Path] = []

    for d in get_dirs_to_initialize():
        rel = d.relative_to(ROOT_DIR)
        if d.exists():
            logger.info(f"目录已经存在: {rel}")
            existed.append(d)
        else:
            try:
                d.mkdir(parents=True, exist_ok=True)
                logger.info(f"成功创建: {rel}")
                created.append(d)
            except OSError as e:
                logger.error(f"创建失败: {rel}: {e}")
                raise  SystemExit(1) from e

    logger.info(f"初始化汇总".center(LINE_WIDTH, '='))

    logger.info("开始检查原始数据集目录".center(LINE_WIDTH, '='))
    raw_status = _check_raw_data_status()

    widths = [32, 12]
    aligns = ['left', 'right']
    logger.info(format_table_row(['目录','状态'], widths, aligns))
    logger.info(format_table_separator(widths))
    for d in created:
        logger.info(format_table_row([str(d.relative_to(ROOT_DIR)), "新建"], widths, aligns))
    for d in existed:
        logger.info(format_table_row([str(d.relative_to(ROOT_DIR)), "已存在"], widths, aligns))

    if not created and not existed:
        logger.info(f"本次目录没有任何变化")

    for status in raw_status:
        logger.info(f"  - {status}")
    logger.info(f"项目初始化完完毕".center(LINE_WIDTH, "="))
    logger.info(f"下一步: 把数据集放到 data/raw/下, 然后运行数据转换脚本")
    logger.info("=" * LINE_WIDTH)

if __name__ == "__main__":
    initialize_project()