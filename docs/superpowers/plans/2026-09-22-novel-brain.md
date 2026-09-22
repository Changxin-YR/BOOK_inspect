# 中文长篇小说外部大脑与质量门禁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建不依赖聊天上下文、可恢复且可验证的中文长篇小说记忆与质量门禁 CLI。

**Architecture:** Python 标准库实现数据模型、JSON/JSONL 存储、确定性审校引擎和 CLI。正式资料、候选资料、运行检查点和上下文恢复包分目录保存；每次运行以输入哈希和阶段结果实现增量与幂等。

**Tech Stack:** Python 3.11+ 标准库、`unittest`、Git 可审阅 JSON/Markdown。

**Spec:** `docs/superpowers/specs/2026-09-22-novel-brain-design.md`

## Global Constraints

- 不破坏已有正文和历史资料；当前仓库没有既有正文，仍保留兼容导入路径。
- 不依赖模型 API；无模型时确定性检查、检索、恢复和门禁可运行。
- 不声明未经官方证实的平台 AI 阈值。
- 未通过终审的候选事实不得进入正式记忆或状态快照。
- 任何正式事实都必须有章节和原文证据。

### Task 1: Data model and storage

**Files:**
- Create: `book_inspect/__init__.py`
- Create: `book_inspect/models.py`
- Create: `book_inspect/store.py`
- Create: `pyproject.toml`

- [ ] 建立 dataclass 模型和 JSON 序列化。
- [ ] 实现原子 JSON 写入、JSONL 追加去重、输入哈希和目录初始化。
- [ ] 运行 `python -m unittest discover -s tests -v` 验证基础存储。

### Task 2: Deterministic inspection engine

**Files:**
- Create: `book_inspect/engine.py`
- Create: `book_inspect/rules.py`

- [ ] 实现字数、段落、对白、句长和中文字符统计。
- [ ] 实现候选事实分层、保护事实、来源证据和关系历史。
- [ ] 实现相关记忆检索、连续性冲突、时间线/世界规则、重复和 AI 症状、文风、梗时代感、读者模式。
- [ ] 实现 `run_check()` 阶段状态机、输入哈希复用和终审晋级。

### Task 3: CLI and recovery artifacts

**Files:**
- Create: `book_inspect/cli.py`
- Create: `book_inspect/__main__.py`
- Create: `rules/platform_rules.json`
- Modify: `README.md`

- [ ] 提供 `init`、`check`、`context`、`resume`、`demo` 命令。
- [ ] 生成轻量 Context Pack 和交接信息。
- [ ] 提供官方平台入口登记而不硬编码传言阈值。

### Task 4: End-to-end verification

**Files:**
- Create: `tests/test_workflow.py`
- Create: `examples/demo_project/`（由 `demo` 生成）

- [ ] 用中文多章节场景验证所有验收项。
- [ ] 模拟中断、输入变化、重复运行和删除索引恢复。
- [ ] 运行完整测试和 demo，读取报告证据后再声称完成。
