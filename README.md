# BOOK_inspect

中文长篇网络小说的外部大脑与质量门禁。它把正文、正式记忆、候选结果、检查报告和恢复状态保存到 Git 可审阅文件中，不依赖上一段 ChatGPT 对话。

## 快速开始

```powershell
python -m book_inspect init .
python -m book_inspect check --root . --chapter novel/chapters/chapter_001.md --min-chars 4000
python -m book_inspect context --root . --chapter novel/chapters/chapter_001.md --task "继续写下一章"
```

如果任务中断，运行目录会保留每个已完成阶段：

```powershell
python -m book_inspect resume --root . --run-id <运行标识>
```

输出位置：

- `novel/chapters/`：正文；不会由检查器覆盖。
- `.book_inspect/memory/facts.json`：正式长期事实，包含来源、层级、状态和历史。
- `.book_inspect/memory/state.json`：当前状态快照。
- `.book_inspect/reports/`：带输入哈希、记忆选择证据、问题和读者反馈的报告。
- `.book_inspect/context/`：轻量 Context Pack，可粘贴到新 ChatGPT 对话。
- `.book_inspect/runs/`：阶段检查点和断点恢复数据。
- `.book_inspect/HANDOFF.md`：会话交接信息。

## 章节事实标记

正文可用一行显式标记高价值事实，避免把普通动作塞进长期记忆：

```text
【事实】林舟|location|黑石城|5
【事实】林舟|injury|右臂骨裂|5
【事实】沈遥|relationship|不信任林舟|4
【伏笔】旧铜铃：铃声会在无月夜响起
```

字段为 `主体|谓词|值|重要性|模式`，模式写 `update` 表示状态演变，旧事实会保留为历史；没有 `update` 且状态键出现互斥值会阻止发布。也可以在章节旁放同名 `.facts.json`，供模型或人工提供结构化事实。

## 内置验证

```powershell
python -m book_inspect demo examples/demo_project
python -m unittest discover -s tests -v
```

`demo` 会生成两个中文章节：第一章形成正式记忆，第二章故意包含地点冲突和认知穿帮，确保阻止门禁真的生效。

平台规则只登记公开官方入口和核验时间，未写入未经官方证实的“AI率阈值”。

ChatGPT 新对话的最短操作协议见 `docs/CHATGPT_WORKFLOW.md`。
检查AI味以及优化其他
