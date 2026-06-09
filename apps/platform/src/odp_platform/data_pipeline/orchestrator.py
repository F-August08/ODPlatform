#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :orchestrator.py
# @Time      :2026/6/9 15:35:16
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :端到端的流程编排器：raw -> yolo txt -> split -> 落盘 -> yaml
"""端到端编排: raw -> yolo txt -> split -> 落盘 -> yaml。"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from odp_platform.common.constants import (
    COVERAGE_HARD_THRESHOLD, COVERAGE_SOFT_THRESHOLD,
    DEFAULT_RANDOM_STATE, DEFAULT_SPLIT_STRATEGY, IMAGE_EXTENSIONS, Task,
)
from odp_platform.common.paths import (
    TRAIN_IMAGES_DIR, TRAIN_LABELS_DIR, VAL_IMAGES_DIR, VAL_LABELS_DIR,
    TEST_IMAGES_DIR, TEST_LABELS_DIR, raw_dataset_root, dataset_yaml_path,
)
from odp_platform.data_pipeline.registry import ConvertOptions, get_converter
from odp_platform.data_pipeline.service import convert_data_to_yolo
from odp_platform.data_pipeline.split.manifest import PairList
from odp_platform.data_pipeline.split.materializer import SplitOutputDirs, materialize
from odp_platform.data_pipeline.split.splitter import split_pairs
from odp_platform.data_pipeline.split.yaml_writer import write_dataset_yaml

logger = logging.getLogger(__name__)

@time_it(logger_instance=logger, name='数据转换',iterations=1)

class DatasetPipeline:
    """端到端编排器。"""

    def __init__(
        self,
        dataset_name: str,
        annotation_format: str,
        task: str = Task.DETECT,
        train_rate: float = 0.8,
        val_rate: float = 0.1,
        classes: Optional[List[str]] = None,
        coco_cls91to80: bool = False,
        random_state: int = DEFAULT_RANDOM_STATE,
        split_strategy: str = DEFAULT_SPLIT_STRATEGY,
    ):
        self.dataset_name = dataset_name
        self.annotation_format = annotation_format
        self.task = task
        self.train_rate = train_rate
        self.val_rate = val_rate
        self.random_state = random_state
        self.split_strategy = split_strategy

        # 入参 classes (不可变) 与 运行时确定的 classes 分开存
        self._user_classes: Optional[List[str]] = classes
        self._final_classes: List[str] = []

        self._options = ConvertOptions(
            task=task, classes=classes, coco_cls91to80=coco_cls91to80,
        )

        # 路径全部从 paths.py 取
        self.raw_root = raw_dataset_root(dataset_name)
        self.raw_images = self.raw_root / "images"
        self.raw_annotations = self.raw_root / "annotations"
        self.output_dirs = SplitOutputDirs(
            train_images=TRAIN_IMAGES_DIR, train_labels=TRAIN_LABELS_DIR,
            val_images=VAL_IMAGES_DIR, val_labels=VAL_LABELS_DIR,
            test_images=TEST_IMAGES_DIR, test_labels=TEST_LABELS_DIR,
        )
        self.yaml_out = dataset_yaml_path(dataset_name)

    def run(self) -> dict:
        """跑完端到端。返回 {counts, yaml}。"""
        logger.info(
            f"开始处理数据集 {self.dataset_name!r} "
            f"(format={self.annotation_format}, task={self.task}, split={self.split_strategy})"
        )

        # 1. 校验 raw 目录 (覆盖率前置在阶段 9 撞墙③ 升级成 fail-fast)
        self._check_raw()

        # 2. 校验 converter 支持当前 task
        entry = get_converter(self.annotation_format)
        if not entry.supports(self.task):
            raise ValueError(
                f"格式 {self.annotation_format!r} 不支持 task={self.task!r}。支持: {entry.supported_tasks}"
            )

        # 3. tempfile 中转: converter 写临时目录, 不污染 data/raw/
        with tempfile.TemporaryDirectory(prefix="odp_pipe_") as tmp:
            staging = Path(tmp) / "labels"
            classes = convert_data_to_yolo(
                input_dir=self.raw_annotations,
                output_labels_dir=staging,
                annotation_format=self.annotation_format,
                options=self._options,
            )
            self._final_classes = classes
            logger.info(f"转换得到 {len(classes)} 个类别")

            # 4. 配对
            pairs = self._pair_images_with_labels(staging)
            logger.info(f"图像-标签配对: {len(pairs)} 对")

            # 4.5 为分层策略构建 {image_stem: [类别名,...]} (random 不读, 但统一构建)
            labels_per_image = self._build_labels_per_image(pairs, classes)

            # 5. 划分 (传 strategy + labels_per_image)
            manifest = split_pairs(
                pairs,
                train_rate=self.train_rate, val_rate=self.val_rate,
                random_state=self.random_state,
                strategy=self.split_strategy,
                labels_per_image=labels_per_image,
            )
            logger.info(f"划分结果: {manifest.summary()}")

            # 6. 落盘
            counts = materialize(manifest, self.output_dirs)

            # 7. 写 yaml
            write_dataset_yaml(
                self.yaml_out,
                dataset_root=self.output_dirs.train_images.parent.parent,
                classes=classes, manifest=manifest,
                dataset_name=self.dataset_name,
                source_format=self.annotation_format, task=self.task,
            )

        return {"counts": counts, "yaml": str(self.yaml_out)}

    # ------------------------------------------------------------
    def _check_raw(self) -> None:
        """目录存在性检查。覆盖率前置在阶段 9 (撞墙③) 补强。"""
        if not self.raw_root.is_dir():
            raise FileNotFoundError(f"数据集目录不存在: {self.raw_root}")
        if not self.raw_images.is_dir():
            raise FileNotFoundError(f"缺少 images 子目录: {self.raw_images}")
        if not self.raw_annotations.is_dir():
            raise FileNotFoundError(f"缺少 annotations 子目录: {self.raw_annotations}")
        self._check_coverage()   # 覆盖率分级检查 (hard-fail / soft-warn / pass)

    def _check_coverage(self) -> None:
        """图像-标注覆盖率检查，按阈值分级响应。

        - coverage < COVERAGE_HARD_THRESHOLD (0.5): fail-fast, 拒绝处理
        - coverage < COVERAGE_SOFT_THRESHOLD (0.9): 警告但继续
        - coverage >= SOFT: 正常通过
        """
        n_images = sum(
            len(list(self.raw_images.glob(f"*{ext}"))) for ext in IMAGE_EXTENSIONS
        )
        n_annos = len(list(self.raw_annotations.glob("*.*")))
        if n_images == 0:
            raise FileNotFoundError(f"{self.raw_images} 下没有任何图像")
        coverage = n_annos / n_images
        if coverage < COVERAGE_HARD_THRESHOLD:
            raise FileNotFoundError(
                f"图像-标注覆盖率 {coverage:.1%} 低于硬阈值 {COVERAGE_HARD_THRESHOLD:.0%}。"
                f" 图像 {n_images} 张, 标注 {n_annos} 个。"
                f" 请检查数据集完整性。"
            )
        elif coverage < COVERAGE_SOFT_THRESHOLD:
            logger.warning(
                f"覆盖率偏低: {n_annos}/{n_images} = {coverage:.1%}"
                f" (低于软阈值 {COVERAGE_SOFT_THRESHOLD:.0%}), 训练效果可能受影响"
            )
        else:
            logger.info(f"覆盖率: {n_annos}/{n_images} = {coverage:.1%}")

    def _pair_images_with_labels(self, labels_dir: Path) -> PairList:
        """按 stem 配对 raw_images/ 下的图像 和 labels_dir 下的 yolo txt。"""
        image_index = {}
        for ext in IMAGE_EXTENSIONS:
            for img in self.raw_images.glob(f"*{ext}"):
                image_index[img.stem] = img
        pairs: PairList = []
        for lbl in sorted(labels_dir.glob("*.txt")):   # sorted: 复现性前提
            img = image_index.get(lbl.stem)
            if img is None:
                logger.debug(f"标签 {lbl.name} 无对应图像, 跳过")
                continue
            pairs.append((img, lbl))
        return pairs

    def _build_labels_per_image(
        self, pairs: PairList, classes: List[str],
    ) -> Dict[str, List[str]]:
        """读每个 yolo txt 的首列 class_id, 映射回类别名。Returns {stem: [类别名,...]}。"""
        result: Dict[str, List[str]] = {}
        for img_path, label_path in pairs:
            names: List[str] = []
            if label_path.exists():
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    cls_id = int(line.split()[0])
                    if 0 <= cls_id < len(classes):
                        names.append(classes[cls_id])
            result[img_path.stem] = names
        return result
