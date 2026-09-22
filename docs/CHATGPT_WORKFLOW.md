# ChatGPT 网页端工作协议

每次新开对话只需要告诉 ChatGPT：仓库地址、当前任务和章节路径。不要把整本小说复制到对话里。

## 继续写下一章

1. 读取 `.book_inspect/memory/state.json`、`.book_inspect/HANDOFF.md` 和当前章节的 `context/<chapter>.json`。
2. 如果 Context Pack 不存在，运行：

   ```powershell
   python -m book_inspect context --root . --chapter novel/chapters/chapter_XXX.md --task "继续写下一章"
   ```

3. 只使用 Context Pack、当前状态、相关设定和最近章节，先写候选正文。
4. 把新增重要事实写入章节事实标记或旁置 `.facts.json`，再运行 `check`。
5. 只有结果为“通过”或“带警告通过”时，才把章节视为正式推进；“阻止发布”时不要声称状态已更新。

## 检查某章

```powershell
python -m book_inspect check --root . --chapter novel/chapters/chapter_XXX.md --min-chars 4000
```

把报告中的问题按位置分组，只修改必要段落。修改正文后重新运行检查；输入哈希变化会让旧阶段失效，正式记忆不会被旧运行覆盖。

## 继续中断任务

读取 `.book_inspect/HANDOFF.md` 找到运行标识，然后运行：

```powershell
python -m book_inspect resume --root . --run-id <运行标识>
```

运行状态、输入哈希、阶段结果和是否已经晋级正式记忆都在 `.book_inspect/runs/`。重复运行同一标识是幂等的。

## 模型职责边界

模型可以提供正文、结构化候选事实和局部修改建议；确定性检查器负责字数、来源、检索、重复、连续性、状态晋级和恢复。任何平台都没有公开可靠的“AI率阈值”时，不把传言写成规则，也不输出伪精确概率。
