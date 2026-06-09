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