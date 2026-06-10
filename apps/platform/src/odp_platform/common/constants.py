"""项目级共享常量——所有模块的"共同词汇表"。

放在这里的标准:
    - 多模块共享 (>= 2 个模块用到)
    - 与具体业务无关 (纯定义, 不含逻辑)
    - 修改频率极低
"""
from __future__ import annotations

from typing import Tuple


# ============================================================
# 图像扩展名 (converter / splitter / report 等模块共享)
# ============================================================
IMAGE_EXTENSIONS: Tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp",
)


# ============================================================
# 标注格式名
# ============================================================
class AnnotationFormat:
    """支持的标注格式 (字符串常量, 供 @register 装饰器直接吃)。"""
    PASCAL_VOC = "pascal_voc"
    COCO       = "coco"
    YOLO       = "yolo"

    @classmethod
    def all(cls) -> Tuple[str, ...]:
        return (cls.PASCAL_VOC, cls.COCO, cls.YOLO)


# ============================================================
# 任务类型
# ============================================================
class Task:
    """模型任务类型。"""
    DETECT  = "detect"
    SEGMENT = "segment"

    @classmethod
    def all(cls) -> Tuple[str, ...]:
        return (cls.DETECT, cls.SEGMENT)


# ============================================================
# 数据集划分策略 (split/ 子系统 + CLI 共享)
# ============================================================
class SplitStrategy:
    """数据集划分策略名 (字符串常量, 供 @register_strategy 装饰器直接吃)。

    L0 random            : 纯随机 (默认, 零额外输入)
    L1 stratified        : 主类别分层 (零依赖, 共现度低时够用)
    L1+ stratified_multilabel : 多标签迭代分层 (同时平衡所有类, 共现度高时用)

    预留 (加文件即可扩展):
        GROUP       = "group"             # L2 分组 (防视频/批次泄漏)
        STRAT_GROUP = "stratified_group"  # L3 分层 + 分组
    """
    RANDOM                = "random"
    STRATIFIED            = "stratified"
    STRATIFIED_MULTILABEL = "stratified_multilabel"

    @classmethod
    def all(cls) -> Tuple[str, ...]:
        return (cls.RANDOM, cls.STRATIFIED, cls.STRATIFIED_MULTILABEL)


DEFAULT_SPLIT_STRATEGY: str = SplitStrategy.RANDOM
"""默认划分策略。RANDOM 不挑数据、零额外输入, 是主流场景的零成本默认。"""


# ============================================================
# 浮点 / 随机
# ============================================================
DEFAULT_RANDOM_STATE: int = 42

RATE_EPSILON: float = 1e-6
"""划分比例的浮点容差。比如 1.0 - 0.7 - 0.3 不等于 0 而是 5.55e-17。"""


# ============================================================
# 数据集覆盖率阈值 (orchestrator 前置 fail-fast)
# ============================================================
COVERAGE_HARD_THRESHOLD: float = 0.5
"""图像-标注覆盖率硬阈值: 低于此值直接终止 (训练必废)。"""

COVERAGE_SOFT_THRESHOLD: float = 0.9
"""图像-标注覆盖率软阈值: 低于此值仅警告。"""


# ============================================================
# 类别平衡性报告阈值 (report.py 使用, 纯提醒, 不拦截)
# ============================================================
CLASS_MIN_IMAGES_HARD: int = 2
"""某类图像数 < 此值: 无论何种分层, 都无法同时进 train/val (主类别策略会把它全归 train)。"""

CLASS_MIN_BOXES_WARN: int = 20
"""某类框数 < 此值: 实例太少, 模型大概率学不好 (经验阈值, 可按数据集体量调)。"""

CLASS_MIN_BOX_SHARE: float = 0.01
"""某类框数占比 < 此值 (默认 1%): 相对其它类严重偏少 (相对阈值, 与绝对阈值互补)。
绝对阈值抓"实例太少", 相对阈值抓"在这个数据集里太边缘"。两者任一触发即提醒。"""

# ---- dataset_statistics 健康阈值 ----
STATS_MIN_BOX_AREA: float = 1e-4         # 归一化面积 < 此值算"近零框"
STATS_MAX_ASPECT_RATIO: float = 20.0     # w/h 或 h/w > 此值算极端长宽比
STATS_MAX_IMBALANCE_RATIO: float = 50.0  # 最多类/最少非空类 实例比 > 此值算严重不均衡

PAIR_MISSING_ERROR_RATIO: float = 0.5  # 确实缺少的图像对占比 > 0，5 此值算错误
PAIR_MISSING_WARN_RATIO: float = 0.05  # 确实缺少的图像对占比 > 0，05 此值算提醒
