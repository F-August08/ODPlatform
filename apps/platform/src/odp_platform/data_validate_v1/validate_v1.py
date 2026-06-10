#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :validate_v1.py
# @Time      :2026/6/10 09:25:52
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  :
# apps/platform/src/odp_platform/data_validation/validate_v1.py
"""第一版: 朴素实现, 4 个 check 全塞一个函数。

这是一个【会被砸掉】的文件——阶段 2 用注册表替换它。
不进 git——见阶段 1.7 的设计点。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

import yaml

from odp_platform.common.constants import IMAGE_EXTENSIONS
from odp_platform.common.paths import DATA_DIR

logger = logging.getLogger(__name__)

# validate() 只允许访问 DATA_DIR 及其子目录, 防止 YAML path/split 字段路径穿越
_ALLOWED_BASE = DATA_DIR.resolve()


def _is_within_base(target: Path) -> bool:
    """检查 target 是否在 _ALLOWED_BASE 之内 (含自身)。"""
    try:
        target.resolve(strict=False).relative_to(_ALLOWED_BASE)
        return True
    except ValueError:
        return False


def validate(yaml_path: Path) -> bool:
    """一坨实现——4 个 check 串到底。

    Returns:
        True  → 全部通过
        False → 任意一项失败
    """
    # ============ check 1: yaml_schema ============
    if not yaml_path.exists():
        logger.error(f"yaml 文件不存在: {yaml_path}")
        return False

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"yaml 解析失败: {e}")
        return False

    if not isinstance(cfg, dict):
        logger.error(f"yaml 顶层不是 dict: {type(cfg).__name__}")
        return False

    names = cfg.get("names")
    nc    = cfg.get("nc")

    # ultralytics 接受两种 names 写法 (新旧都得支持):
    #   list[str]:        names: [cat, dog, bird]
    #   dict[int, str]:   names: {0: cat, 1: dog, 2: bird}   ← D3 yaml_writer 出的就是这种
    if isinstance(names, list) and names and all(isinstance(n, str) and n for n in names):
        names_count = len(names)
    elif (isinstance(names, dict) and names
            and all(isinstance(k, int) for k in names.keys())
            and all(isinstance(v, str) and v for v in names.values())):
        names_count = len(names)
    else:
        logger.error("names 缺失或不是合法的 list[str] / dict[int, str]")
        return False

    if not isinstance(nc, int) or nc <= 0:
        logger.error(f"nc 缺失或不是正整数: {nc!r}")
        return False

    if names_count != nc:
        logger.error(f"nc ({nc}) 跟 names 长度 ({names_count}) 不一致")
        return False

    logger.info(f"[PASS] yaml_schema: nc={nc}, names_count={names_count}")

    # 解析 data_root (yaml.path 字段, 或 yaml 同级目录兜底)
    path_str = cfg.get("path")
    if path_str:
        data_root = Path(path_str)
        if not data_root.is_absolute():
            data_root = (yaml_path.parent / data_root).resolve()
    else:
        data_root = yaml_path.parent.resolve()

    # ── 沙箱: 拒绝越界访问 ──
    if not _is_within_base(data_root):
        logger.error(
            f"[FAIL] 路径穿越: data_root={data_root} 不在允许范围 {_ALLOWED_BASE} 之内。"
            f" 请检查 yaml 中 path 字段。"
        )
        return False

    def _resolve_split_dir(split_rel: str) -> Path | None:
        """解析并校验单个 split 目录。返回 None 表示越界。"""
        if Path(split_rel).is_absolute():
            d = Path(split_rel).resolve()
        else:
            d = (data_root / split_rel).resolve()
        if not _is_within_base(d):
            logger.error(
                f"[FAIL] 路径穿越: split 目录 {d} 越界 (yaml 字段 {split_rel!r})。"
            )
            return None
        return d

    # ============ check 2: pair_existence ============
    missing_total = 0
    images_total  = 0
    for split in ("train", "val", "test"):
        split_rel = cfg.get(split)
        if not split_rel:
            continue
        split_dir = _resolve_split_dir(split_rel)
        if split_dir is None:
            return False
        if not split_dir.exists():
            continue
        for ext in IMAGE_EXTENSIONS:
            for img in split_dir.glob(f"*{ext}"):
                images_total += 1
                # YOLO 默认布局: images/<split>/foo.jpg → labels/<split>/foo.txt
                parts = list(img.parts)
                for i in range(len(parts) - 1, -1, -1):
                    if parts[i] == "images":
                        parts[i] = "labels"
                        break
                label = Path(*parts[:-1]) / (img.stem + ".txt")
                if not label.exists():
                    missing_total += 1

    if missing_total > 0:
        logger.error(f"[FAIL] pair_existence: {missing_total}/{images_total} 张图无标签")
        return False
    logger.info(f"[PASS] pair_existence: {images_total} 张图都有标签")

    # ============ check 3: label_format ============
    for split in ("train", "val", "test"):
        split_rel = cfg.get(split)
        if not split_rel:
            continue
        split_dir = _resolve_split_dir(split_rel)
        if split_dir is None:
            return False
        if not split_dir.exists():
            continue
        for ext in IMAGE_EXTENSIONS:
            for img in split_dir.glob(f"*{ext}"):
                parts_p = list(img.parts)
                for i in range(len(parts_p) - 1, -1, -1):
                    if parts_p[i] == "images":
                        parts_p[i] = "labels"
                        break
                label = Path(*parts_p[:-1]) / (img.stem + ".txt")
                if not label.exists():
                    continue
                with open(label, "r", encoding="utf-8") as f:
                    for line_no, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split()
                        if len(parts) != 5:
                            logger.error(
                                f"[FAIL] label_format: {label.name} 第{line_no}行字段数!=5"
                            )
                            return False
                        try:
                            cls_id = int(parts[0])
                            coords = [float(x) for x in parts[1:5]]
                        except ValueError:
                            logger.error(
                                f"[FAIL] label_format: {label.name} 第{line_no}行类型错"
                            )
                            return False
                        if not (0 <= cls_id < nc):
                            logger.error(
                                f"[FAIL] label_format: {label.name} 第{line_no}行 cls_id={cls_id} 越界 (nc={nc})"
                            )
                            return False
                        if not all(0.0 <= c <= 1.0 for c in coords):
                            logger.error(
                                f"[FAIL] label_format: {label.name} 第{line_no}行坐标越界"
                            )
                            return False
    logger.info(f"[PASS] label_format")

    # ============ check 4: split_uniqueness ============
    stems_by_split: Dict[str, set] = {}
    for split in ("train", "val", "test"):
        split_rel = cfg.get(split)
        if not split_rel:
            continue
        split_dir = _resolve_split_dir(split_rel)
        if split_dir is None:
            return False
        if not split_dir.exists():
            continue
        stems = set()
        for ext in IMAGE_EXTENSIONS:
            stems.update(p.stem for p in split_dir.glob(f"*{ext}"))
        stems_by_split[split] = stems

    for s1, s2 in [("train", "val"), ("train", "test"), ("val", "test")]:
        if s1 not in stems_by_split or s2 not in stems_by_split:
            continue
        common = stems_by_split[s1] & stems_by_split[s2]
        if common:
            logger.error(
                f"[FAIL] split_uniqueness: {s1} 和 {s2} 之间有 {len(common)} 张重复——数据泄露!"
            )
            return False
    logger.info(f"[PASS] split_uniqueness")

    logger.info("✓ 全部 4 项检查通过")
    return True


if __name__ == "__main__":
    import sys
    from odp_platform.common.paths import dataset_yaml_path

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) != 2:
        print("用法: python -m odp_platform.data_validation.validate_v1 <数据集名>")
        print("例如: python -m odp_platform.data_validation.validate_v1 rsod")
        sys.exit(1)

    dataset_name = sys.argv[1]
    yaml_path    = dataset_yaml_path(dataset_name)
    ok = validate(yaml_path)
    sys.exit(0 if ok else 1)
