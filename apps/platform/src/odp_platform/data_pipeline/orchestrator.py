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
from collections import Counter
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
from odp_platform.common.performance_utils import time_it
from odp_platform.common.string_utils import format_table_row, format_table_separator, get_display_width
from odp_platform.data_pipeline.registry import ConvertOptions, get_converter
from odp_platform.data_pipeline.service import convert_data_to_yolo
from odp_platform.data_pipeline.split.manifest import PairList, SplitManifest
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

        # 路径全部从 paths.py 取 (先设 raw_root, _auto_classes 需要用到)
        self.raw_root = raw_dataset_root(dataset_name)
        self.raw_images = self.raw_root / "images"
        self.raw_annotations = self.raw_root / "annotations"

        # 入参 classes (不可变) 与 运行时确定的 classes 分开存
        self._user_classes: Optional[List[str]] = classes
        self._final_classes: List[str] = []

        # yolo 格式自动从 classes.txt 探测类别名
        if not classes:
            classes = self._auto_classes()

        self._options = ConvertOptions(
            task=task, classes=classes, coco_cls91to80=coco_cls91to80,
        )
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

            # 5.5 打印数据集统计 (类别分布 + 划分详情)
            self._print_statistics(pairs, classes, manifest)

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
    # 统计
    # ------------------------------------------------------------
    def _count_instances(self, pairs: PairList) -> Counter:
        """统计每对 (image, label) 中各 class_id 的实例数。"""
        counter: Counter = Counter()
        for _, label_path in pairs:
            for line in label_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                cls_id = int(line.split()[0])
                counter[cls_id] += 1
        return counter

    def _print_statistics(
        self,
        pairs: PairList,
        classes: List[str],
        manifest: SplitManifest,
    ) -> None:
        """打印完整数据集统计: 类别分布 + 划分详情 + 各子集分布。"""
        LINE = 80
        n_classes = len(classes)

        # 预先计算所有表格共享的动态列宽
        id_col_w = max(len(str(n_classes - 1)), 2) + 2  # ID 列
        num_col_w = max(                                   # 数字列 (train/val/test 共用)
            len("train"), len("val"), len("test"),
            len("实例数"),
        ) + 2

        # ── 全局统计 ──
        global_counts = self._count_instances(pairs)
        total_instances = sum(global_counts.values())
        total_images = len(pairs)

        logger.info("")
        logger.info("=" * LINE)
        logger.info("数据集统计概览".center(LINE))
        logger.info("=" * LINE)
        logger.info(f"  数据集:  {self.dataset_name}")
        logger.info(f"  格式:    {self.annotation_format}  →  YOLO")
        logger.info(f"  任务:    {self.task}")
        logger.info(f"  类别数:  {n_classes}")
        logger.info(f"  图像:    {total_images} 张")
        logger.info(f"  实例:    {total_instances} 个")
        if total_images > 0:
            logger.info(f"  密度:    {total_instances / total_images:.1f} 实例/图")

        # ── 类别分布 ──
        logger.info("")
        logger.info(f"类别分布 (共 {n_classes} 类):")
        logger.info("-" * LINE)

        # 动态列宽: 根据实际类别名 + 数字宽度自适应
        cls_name_w = max((get_display_width(c) for c in classes), default=10)
        cls_name_col = max(cls_name_w, get_display_width("类别名")) + 2
        cls_count_w = max(len(str(max(global_counts.values(), default=0))), get_display_width("实例数")) + 2
        cls_pct_w = max(5, get_display_width("占比")) + 2      # "xx.x%" 最长 5

        widths = [id_col_w, cls_name_col, cls_count_w, cls_pct_w]
        aligns = ['left', 'left', 'right', 'right']
        logger.info(format_table_row(['ID', '类别名', '实例数', '占比'], widths, aligns))
        logger.info(format_table_separator(widths))

        for cls_id in sorted(global_counts.keys(), key=lambda k: global_counts[k], reverse=True):
            count = global_counts[cls_id]
            name = classes[cls_id] if cls_id < n_classes else f"class_{cls_id}"
            pct = f"{count / total_instances * 100:.1f}%"
            logger.info(format_table_row(
                [str(cls_id), name, str(count), pct], widths, aligns,
            ))

        # ── 划分结果 ──
        n_train = len(manifest.train)
        n_val = len(manifest.val)
        n_test = len(manifest.test)
        test_rate = max(0.0, 1.0 - self.train_rate - self.val_rate)

        train_inst = sum(self._count_instances(manifest.train).values())
        val_inst = sum(self._count_instances(manifest.val).values())
        test_inst = sum(self._count_instances(manifest.test).values())

        logger.info("")
        logger.info("数据集划分结果".center(LINE))
        logger.info("-" * LINE)

        # 动态列宽: 根据实际数值 + 中文表头计算
        split_label_w = max(get_display_width("合计"), len("train"), len("val"), len("test")) + 2
        split_img_w = max(len(str(total_images)), get_display_width("图像数")) + 2
        split_inst_w = max(len(str(total_instances)), get_display_width("实例数")) + 2
        split_pct_w = max(5, get_display_width("占比")) + 2

        split_widths = [split_label_w, split_img_w, split_inst_w, split_pct_w]
        split_aligns = ['left', 'right', 'right', 'right']
        logger.info(format_table_row(
            ['', '图像数', '实例数', '占比'], split_widths, split_aligns,
        ))
        logger.info(format_table_separator(split_widths))
        logger.info(format_table_row(
            ['train', str(n_train), str(train_inst),
             f"{self.train_rate:.0%}"], split_widths, split_aligns,
        ))
        logger.info(format_table_row(
            ['val', str(n_val), str(val_inst),
             f"{self.val_rate:.0%}"], split_widths, split_aligns,
        ))
        logger.info(format_table_row(
            ['test', str(n_test), str(test_inst),
             f"{test_rate:.0%}"], split_widths, split_aligns,
        ))
        logger.info(format_table_separator(split_widths))
        logger.info(format_table_row(
            ['合计', str(total_images), str(total_instances), '100%'],
            split_widths, split_aligns,
        ))

        # ── 各子集类别分布 ──
        train_counter = self._count_instances(manifest.train)
        val_counter = self._count_instances(manifest.val)
        test_counter = self._count_instances(manifest.test)

        # 动态计算列宽: 根据实际类别名 + 数字宽度自适应
        max_name_w = max((get_display_width(c) for c in classes), default=10)
        name_col_w = max(max_name_w, get_display_width("类别")) + 2
        dist_num_w = max(
            len(str(max(train_counter.values(), default=0))),
            len(str(max(val_counter.values(), default=0))),
            len(str(max(test_counter.values(), default=0))),
            len("train"), len("val"), len("test"),
        ) + 2

        logger.info("")
        logger.info("各子集类别分布".center(LINE))
        logger.info("-" * LINE)
        dist_widths = [id_col_w, name_col_w, dist_num_w, dist_num_w, dist_num_w]
        dist_aligns = ['left', 'left', 'right', 'right', 'right']
        logger.info(format_table_row(
            ['ID', '类别', 'train', 'val', 'test'], dist_widths, dist_aligns,
        ))
        logger.info(format_table_separator(dist_widths))

        for cls_id in sorted(global_counts.keys(), key=lambda k: global_counts[k], reverse=True):
            name = classes[cls_id] if cls_id < n_classes else f"class_{cls_id}"
            logger.info(format_table_row([
                str(cls_id), name,
                str(train_counter.get(cls_id, 0)),
                str(val_counter.get(cls_id, 0)),
                str(test_counter.get(cls_id, 0)),
            ], dist_widths, dist_aligns))

        logger.info("=" * LINE)
        logger.info(f"[PASS] 统计完成 — {total_images} 张图像, {total_instances} 个实例, "
                    f"train/val/test = {n_train}/{n_val}/{n_test}")
        logger.info("=" * LINE)

    # ------------------------------------------------------------
    def _auto_classes(self) -> Optional[List[str]]:
        """自动从 classes.txt 读取类别名 (yolo 格式常用约定)。

        data/raw/<dataset>/classes.txt, 每行一个类别名。
        非 yolo 格式不需要, 返回 None 让 converter 自己探测。
        """
        classes_txt = self.raw_root / "classes.txt"
        if classes_txt.is_file():
            names = [
                line.strip()
                for line in classes_txt.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if names:
                logger.info(f"从 {classes_txt.name} 自动读取到 {len(names)} 个类别: {names}")
                return names
        return None

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
