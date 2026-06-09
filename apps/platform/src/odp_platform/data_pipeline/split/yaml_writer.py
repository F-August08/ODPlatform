#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :yaml_writer.py
# @Time      :2026/6/9 14:39:06
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :生成yaml文件。包含元数据

from __future__ import  annotations
import logging
from datetime import  datetime
from pathlib import Path
from typing import List
import yaml

from odp_platform.data_pipeline.split.manifest import SplitManifest

logger = logging.getLogger(__name__)

def write_dataset_yaml(
        yaml_path: Path,
        *,
        dataset_root: Path,
        classes: List[str],
        manifest: SplitManifest,
        dataset_name: str,
        source_format: str,
        task: str,
) -> None:
    """
    生成yaml文件。包含元数据
    """
    doc = {
        "path": str(dataset_root.resolve()),
        "train": "train/images",
        "val": "val/images",
        "test": "test/images",
        "nc": len(classes),
        "names": {i: name for i, name in enumerate(classes)},

        "odp_meta": {
            "dataset": dataset_name,
            'source_format': source_format,
            "task": task,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "split":{
                "strategy": manifest.strategy,
                "train_rate": round(manifest.train_rate, 6),
                "val_rate": round(manifest.val_rate, 6),
                "test_rate": round(manifest.test_rate, 6),
                "random_state": manifest.random_state,
                "counts": manifest.summary()
            },
            "schema_version": 1,
        }
    }
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with yaml_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    logger.info(f"已经写入dataset yaml: {yaml_path}")





