# label_format Check 设计规格

> 日期: 2026-06-10
> 状态: 待实现
> 依赖: DatasetSnapshot (snapshot.py), CheckContext (registry.py)

## 1. 目标

在 `data_validation/checks/` 下新增 `label_format.py`，验证 YOLO 标注文件内容的格式合法性。

**核心问题：** 现有 `yaml_schema`（验证配置文件）和 `pair_existence`（验证文件存在性）都没有检查标注文件**内部**的格式正确性。无效的标注行会导致训练时静默跳过或梯度异常。

## 2. 检查范围

遍历 `snapshot.labels_per_split` 中所有 split 的所有标注文件，逐行检查 YOLO 格式。

## 3. 检查项（单行维度，共 6 项）

| # | 检查项 | 条件 | 示例非法行 |
|---|--------|------|-----------|
| 1 | 列数 | `len(parts) != 5` | `0 0.5 0.5` |
| 2 | 数值类型 | 任一列无法 parse 为 float | `cat 0.5 0.5 0.1 0.1` |
| 3 | class_id 整数 | `int(cls) != cls` 或 `cls < 0` | `1.5 0.5 0.5 0.1 0.1` |
| 4 | 坐标范围 | x_center, y_center ∉ [0, 1] | `0 1.2 0.5 0.1 0.1` |
| 5 | 宽高 > 0 | width ≤ 0 或 height ≤ 0 | `0 0.5 0.5 0.0 0.1` |
| 6 | 宽高 ≤ 1 | width > 1 或 height > 1 | `0 0.5 0.5 1.5 0.1` |

前 6 行空行/纯空白行静默跳过，不计入统计。

检查短路：单行遇到第一个错误即记录该行，不再检查该行后续项（一行多个错误时只报第一个）。

## 4. 错误类型常量

```python
BAD_COLUMN_COUNT       = "wrong_column_count"
NON_NUMERIC            = "non_numeric"
CLASS_NOT_INTEGER      = "class_not_integer"
COORD_OUT_OF_RANGE     = "coordinate_out_of_range"
DIMENSION_ZERO_OR_NEG  = "dimension_zero_or_negative"
DIMENSION_EXCEEDS_ONE  = "dimension_exceeds_one"
FILE_READ_ERROR        = "file_read_error"
```

## 5. 严重程度分级

沿用 `pair_existence` 的比例阈值模式，新增常量写入 `constants.py`：

```python
LABEL_FORMAT_ERROR_RATIO: float = 0.10   # 超过 10% 的标注文件有格式错误 → ERROR
LABEL_FORMAT_WARN_RATIO:  float = 0.01   # 超过 1% → WARNING，≤1% → INFO
```

| 条件 | 严重级别 | 语义 |
|------|---------|------|
| `bad_files_ratio == 0` | PASS | 全部标注文件格式合法 |
| `0 < bad_files_ratio <= 0.01` | INFO | 极少数瑕疵，不影响训练 |
| `0.01 < bad_files_ratio <= 0.10` | WARNING | 需人工 review |
| `bad_files_ratio > 0.10` | ERROR | 数据质量严重不达标，CI 阻断 |

分母 `total_labels` 为被检查的标注文件总数（有对应图像的）。如果没有标注文件（空数据集），返回 INFO 级空结果。

## 6. CheckResult 结构

### details

```python
{
    "total_labels":       2562,   # 被检查的标注文件总数
    "total_lines":        30125,  # 非空行总数
    "bad_files_count":    15,     # 存在至少一行错误的文件数
    "bad_files_ratio":    0.0059, # bad_files_count / total_labels
    "bad_lines_count":    23,     # 坏行总数
    "error_counts": {             # 按错误类型统计
        "wrong_column_count":      5,
        "non_numeric":             3,
        "class_not_integer":       2,
        "coordinate_out_of_range": 8,
        "dimension_zero_or_negative": 4,
        "dimension_exceeds_one":   1,
        "file_read_error":         0,
    },
    "bad_examples": [             # 最多 10 条示例 (DETAILS_PREVIEW_LIMIT)
        {
            "file":      "data/train/labels/img_001.txt",
            "line_no":   3,
            "raw_line":  "0 1.2 0.5 0.1 0.1",
            "error_type": "coordinate_out_of_range",
        },
        ...
    ],
}
```

### summary 示例

- PASS: `"全部 2562 个标注文件格式合法 (共 30125 行)"`
- INFO: `"2562 个文件中 8 个有格式错误 (0.31%), 共 12 行问题"`
- WARNING: `"2562 个文件中 87 个有格式错误 (3.40%), 共 103 行问题"`
- ERROR: `"2562 个文件中 421 个有格式错误 (16.43%), 共 512 行问题"`

## 7. 异常处理

- **文件读取失败**（权限、编码）：不抛异常，记录为 `file_read_error`，该文件计入 `bad_files_count`
- **空文件**：0 行，不报错也不计入 bad_files
- **空数据集**（无 label 文件）：返回 INFO 级结果，`summary="数据集无标注文件可供检查"`

## 8. 性能考量

- 逐文件全文读取，O(总行数)
- 单线程同步执行，与现有 check 风格一致
- `DETAILS_PREVIEW_LIMIT = 10`：bad_examples 最多存 10 条，只收集不筛选

## 9. 文件清单

| 操作 | 文件 |
|------|------|
| 新增 | `data_validation/checks/label_format.py` |
| 修改 | `common/constants.py` — 加 `LABEL_FORMAT_ERROR_RATIO` / `LABEL_FORMAT_WARN_RATIO` |
| 无需修改 | `registry.py`（自动发现）、`service.py`（不改框架） |

## 10. 测试要点

- 全合法文件 → PASS
- 含各类错误行的文件 → 按比例分级
- 空行不干扰统计
- 文件不存在 / 无权限 → file_read_error
- 无标注文件的空数据集 → INFO
- 单行多错误 → 只报第一个
