from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .engine import restore_context, run_check
from .store import ProjectStore


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def make_demo(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    store = ProjectStore(root)
    store.init()
    (root / "novel" / "chapters" / "chapter_001.md").write_text(
        """【事实】林舟|location|黑石城|5\n【事实】林舟|injury|右臂骨裂|5\n【事实】沈遥|relationship|不信任林舟|4\n【伏笔】旧铜铃：铃声会在无月夜响起\n\n林舟在雨里抵达黑石城，右臂的疼痛让他握不住刀。沈遥没有替他开门，只把一盏灯放在门槛上。\n\n“你从哪里知道铜铃的？”沈遥问。林舟没有回答。远处的城墙传来三声钟响，门外留下了一行湿脚印。\n""" + "雨声压过了街上的脚步。" * 300, encoding="utf-8")
    (root / "novel" / "chapters" / "chapter_002.md").write_text(
        """【事实】林舟|location|白鹿城|5\n【事实】林舟|location|黑石城|5\n【事实】林舟|injury|右臂骨裂|5\n【认知穿帮】沈遥提前知道了尚未揭露的铜铃秘密\n\n与此同时，林舟沉默片刻。与此同时，沈遥沉默片刻。与此同时，门外的人沉默片刻。\n\n但他不知道的是，真正的敌人已经在城门之外。""" + "然而" * 10 + "。" * 50, encoding="utf-8")
    store.write_json("config.json", {"min_effective_chars": 200, "context_limit": 40, "recent_chapters": 3, "style_profile": "style.json", "world_rules": ["无月夜铜铃才会响"]})


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="book-inspect", description="中文长篇小说外部大脑与质量门禁")
    sub = command.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="初始化项目目录")
    init.add_argument("path", nargs="?", default=".")
    check = sub.add_parser("check", help="检查章节并在通过后晋级正式记忆")
    check.add_argument("--root", default=".")
    check.add_argument("--chapter", required=True, help="章节文件路径，相对项目根目录")
    check.add_argument("--name", help="章节标识，默认使用文件名")
    check.add_argument("--min-chars", type=int)
    check.add_argument("--run-id")
    check.add_argument("--stop-after", choices=["stats", "context", "facts", "continuity", "style", "reader"])
    context = sub.add_parser("context", help="生成轻量恢复上下文")
    context.add_argument("--root", default=".")
    context.add_argument("--chapter", required=True)
    context.add_argument("--task", default="继续之前的任务")
    resume = sub.add_parser("resume", help="从运行检查点继续")
    resume.add_argument("--root", default=".")
    resume.add_argument("--run-id", required=True)
    demo = sub.add_parser("demo", help="生成并运行内置中文测试场景")
    demo.add_argument("path", nargs="?", default="examples/demo_project")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "init":
        ProjectStore(args.path).init()
        print(f"initialized: {Path(args.path).resolve()}")
        return 0
    if args.command == "demo":
        root = Path(args.path).resolve()
        make_demo(root)
        store = ProjectStore(root)
        first = run_check(store, "novel/chapters/chapter_001.md", "chapter_001", minimum=200)
        second = run_check(store, "novel/chapters/chapter_002.md", "chapter_002", minimum=200)
        print(_json({"root": str(root), "chapter_001": first, "chapter_002": second}))
        return 0 if second["status"] != "阻止发布" else 1
    if args.command == "check":
        store = ProjectStore(args.root)
        try:
            report = run_check(store, args.chapter, args.name, args.min_chars, args.run_id, args.stop_after)
        except InterruptedError as error:
            print(str(error))
            return 2
        print(_json(report))
        return 0 if report["status"] != "阻止发布" else 1
    if args.command == "resume":
        store = ProjectStore(args.root)
        run = store.load_run(args.run_id)
        if not run:
            print(f"run not found: {args.run_id}")
            return 2
        report = run_check(store, run["chapter_path"], run["chapter"], run_id=args.run_id)
        print(_json(report))
        return 0 if report["status"] != "阻止发布" else 1
    if args.command == "context":
        store = ProjectStore(args.root)
        print(_json(restore_context(store, args.chapter, args.task)))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
