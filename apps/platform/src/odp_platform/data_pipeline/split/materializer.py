#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :materializer.py
# @Time      :2026/6/9 14:26:58
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :

from __future__ import  annotations
import logging
import shutil
from dataclasses import  dataclass
from pathlib import Path

from odp_platform.data_pipeline.split.manifest import PairList, SplitManifest

logger = logging.getLogger(__name__)

@dataclass
class SplitOutputDirs:
    train_images: Path
    train_labels: Path
    val_images: Path
    val_labels: Path
    test_images: Path
    test_labels: Path

    def mkdir_all(self) -> None:
        for p in (
            self.train_images,
            self.train_labels,
            self.val_images,
            self.val_labels,
            self.test_images,
            self.test_labels,
        ):
            p.mkdir(parents=True, exist_ok=True)

def materialize(manifest: SplitManifest, output_dirs: SplitOutputDirs) -> dict:
    output_dirs.mkdir_all()
    counts = {
        "train": _copy_pairs(manifest.train, output_dirs.train_images, output_dirs.train_labels),
        "val": _copy_pairs(manifest.val, output_dirs.val_images, output_dirs.val_labels),
        "test": _copy_pairs(manifest.test, output_dirs.test_images, output_dirs.test_labels),
    }
    logger.info(f"Copied {counts} pairs to {output_dirs}")
    return counts



def _copy_pairs(pairs: PairList, images_dir: Path, labels_dir: Path) -> int:
    n = 0
    for img, lbl in pairs:
        shutil.copy2(img, images_dir / img.name)
        shutil.copy2(lbl, labels_dir / lbl.name)
        n += 1
    return n