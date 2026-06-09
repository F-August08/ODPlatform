# 项目重置工具 设计规格

> 日期: 2026-06-08
> 状态: 待审核

## 概述

提供一个 CLI 工具，将项目恢复到初始化状态。清理运行时产生的日志、数据、模型、训练产物，
并在 `full` 级别下自动重新运行初始化。

## 核心约束：可删除 vs 不可删除

### 不可删除（硬编码白名单）

| 路径 | 原因 |
|------|------|
| `apps/platform/src/` | 平台源码 |
| `apps/desktop/` | 桌面端源码 |
| `apps/web-backend/` | Web 后端源码 |
| `apps/web-frontend/` | Web 前端源码 |
| `packages/shared-schemas/` | 共享 Schema 包源码 |
| `tests/`（顶层） | E2E 测试源码 |
| `apps/platform/tests/` | Platform 单元测试源码 |
| `docs/` | **架构决策记录 (ADR)** 及所有文档 |
| `scripts/` | 工程脚本（含 `init_project.py`） |
| `*.md`（README 等） | 项目文档 |
| `.odp-workspace` | 工作区标记文件 |
| `.gitignore` | Git 配置 |
| `pyproject.toml` | 项目配置 |
| `apps/*/pyproject.toml` | 各端配置 |
| `.git/` | Git 仓库 |

### 可删除

| 路径 | 类型 | 说明 |
|------|------|------|
| `apps/platform/logging/` 下的 `.log` 文件 | 运行时产物 | 每次操作生成的日志 |
| `data/` 全部内容 | 运行时产物 | 数据集（应走外部存储） |
| `models/` 全部内容 | 运行时产物 | 模型权重（应走外部存储） |
| `runs/` 全部内容 | 运行时产物 | 训练运行结果 |
| `apps/platform/configs/` | 初始化创建 | 目前为空目录 |

## 三个重置级别

| 级别 | 清理内容 | 重新初始化？ |
|------|----------|-------------|
| `logs` | 仅删除 `apps/platform/logging/` 下的 `.log` 文件 | 否 |
| `runtime` | logs 的全部 + `data/` + `models/` + `runs/` + `apps/platform/configs/` | 否 |
| `full` | runtime 的全部 + 删除目录本身，然后自动调用 `initialize_project()` | **是** |

## 文件位置

```
scripts/
├── __init__.py
├── init_project.py      # 已存在
└── reset_project.py     # 新增
```

## CLI 接口

```bash
python scripts/reset_project.py --level {logs|runtime|full} [--dry-run] [--yes]
```

| 参数 | 说明 |
|------|------|
| `--level` | 重置级别，必选 |
| `--dry-run` | 仅列出将删除的内容，不执行 |
| `--yes` | 跳过确认提示（适合 CI/脚本化） |

## 安全机制

### 三层防护

1. **硬编码白名单** — 脚本中显式定义"绝对不可删除"的路径列表，删除前交叉验证
2. **交互确认** — 默认显示摘要并要求输入 `yes` 确认（`--yes` 跳过）
3. **`--dry-run`** — 预览模式，只列不删

### 白名单匹配策略

- 精确匹配：`docs/`、`scripts/`、`.odp-workspace`
- 前缀匹配：`apps/platform/src/` 匹配其下所有文件
- Glob 匹配：`**/README.md`、`**/pyproject.toml`

## 执行流程

```
python scripts/reset_project.py --level full
       │
       ▼
┌─ 1. 确定清理范围（根据 --level）
│
├─ 2. 收集待删除列表（遍历目录树，记录路径和大小）
│
├─ 3. 白名单交叉验证
│      命中白名单 → 标记"受保护，跳过"并警告
│      未命中 → 加入删除队列
│
├─ 4. 显示摘要并请求确认 (dry-run 到此结束)
│      ┌────────────────────────────────────────┐
│      │ 将删除:                                │
│      │   data/raw/         (N 个文件)          │
│      │   data/train/       (N 个文件)          │
│      │   ...                                  │
│      │   日志文件: N 个                        │
│      │   总计: N 个目录, N 个文件              │
│      │                                        │
│      │ 将保留(受保护):                         │
│      │   apps/platform/src/                   │
│      │   docs/                                │
│      │   ...                                  │
│      │                                        │
│      │ 输入 yes 确认:                          │
│      └────────────────────────────────────────┘
│
├─ 5. 执行删除（先删文件，再删目录）
│
├─ 6. (仅 full) 重新初始化 → 调用 initialize_project()
│
└─ 7. 输出汇总报告
```

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 待删除路径命中白名单 | 跳过，输出警告，继续执行 |
| 文件/目录删除失败 | 记录错误，继续处理剩余项，最后汇总 |
| 重新初始化失败 | 报告错误，提示手动运行 `python scripts/init_project.py` |
| 工作区 marker 找不到 | 直接终止，与 `init_project.py` 行为一致 |

## 日志

- 操作日志写入 `apps/platform/logging/Reset_project/`（与 `Init_project/` 同级）
- 复用现有 `logging_utils.get_logger()` 模式

## 技术依赖

- 复用 `odp_platform.common.paths` 中的路径定义（`ROOT_DIR`、`LOGGING_DIR`、`DATA_DIR`、`MODELS_DIR`、`RUNS_DIR` 等）
- 复用 `odp_platform.cli.init_project.initialize_project()`
- 复用 `odp_platform.common.logging_utils.get_logger()`
- 仅使用 Python 标准库（`pathlib`、`argparse`、`shutil`、`logging`）
