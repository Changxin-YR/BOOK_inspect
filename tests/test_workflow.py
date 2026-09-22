from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from book_inspect.engine import build_context, run_check
from book_inspect.models import Source
from book_inspect.rules import _make_fact
from book_inspect.store import ProjectStore


def chapter(root: Path, name: str, text: str) -> Path:
    path = root / "novel" / "chapters" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root)
        self.store.init()

    def tearDown(self):
        self.temp.cleanup()

    def test_memory_extraction_excludes_trivial_and_commits_after_pass(self):
        text = """【事实】林舟|location|黑石城|5
【事实】林舟|injury|右臂骨裂|5
林舟吃饭，喝水，天气很好。

林舟推开城门，门后亮着一盏灯。“你来了？”沈遥问。"""
        path = chapter(self.root, "chapter_001", text)
        report = run_check(self.store, path, "chapter_001", minimum=30)
        self.assertIn(report["status"], {"通过", "带警告通过"})
        self.assertLess(report["stats"]["effective_chars"], len(text.replace("\n", "")))
        facts = self.store.load_facts()
        self.assertEqual({fact.value for fact in facts}, {"黑石城", "右臂骨裂"})
        self.assertTrue(all(fact.source.chapter == "chapter_001" for fact in facts))
        state = self.store.load_state()
        self.assertEqual(state["current_chapter"], 1)

    def test_conflict_blocks_and_does_not_pollute_formal_memory(self):
        first = chapter(self.root, "chapter_001", "【事实】林舟|location|黑石城|5\n" + "林舟推门。" * 30)
        run_check(self.store, first, "chapter_001", minimum=50)
        second = chapter(self.root, "chapter_002", "【事实】林舟|location|白鹿城|5\n【事实】林舟|location|黑石城|5\n" + "【认知穿帮】沈遥提前知道铜铃秘密\n" + "林舟继续赶路。" * 30)
        report = run_check(self.store, second, "chapter_002", minimum=50)
        self.assertEqual(report["status"], "阻止发布")
        self.assertFalse(any(fact.source.chapter == "chapter_002" for fact in self.store.load_facts()))
        self.assertTrue(any(issue["code"] == "fact_conflict" for issue in report["issues"]))

    def test_minimum_count_is_hard_gate(self):
        path = chapter(self.root, "chapter_001", "【事实】林舟|location|黑石城|5\n太短。")
        report = run_check(self.store, path, "chapter_001", minimum=4000)
        self.assertEqual(report["status"], "阻止发布")
        self.assertTrue(any(issue["code"] == "word_count" for issue in report["issues"]))
        self.assertEqual(self.store.load_facts(), [])

    def test_resume_idempotence_and_input_invalidation(self):
        path = chapter(self.root, "chapter_001", "【事实】林舟|location|黑石城|5\n" + "林舟推门。" * 30)
        with self.assertRaises(InterruptedError):
            run_check(self.store, path, "chapter_001", minimum=50, stop_after="context")
        runs = list((self.root / ".book_inspect" / "runs").glob("*.json"))
        self.assertEqual(len(runs), 1)
        run_id = json.loads(runs[0].read_text(encoding="utf-8"))["run_id"]
        report = run_check(self.store, path, "chapter_001", minimum=50, run_id=run_id)
        self.assertNotEqual(report["status"], "阻止发布")
        run_check(self.store, path, "chapter_001", minimum=50, run_id=run_id)
        self.assertEqual(len(self.store.load_facts()), 1)
        path.write_text(path.read_text(encoding="utf-8") + "新增变化。", encoding="utf-8")
        changed = run_check(self.store, path, "chapter_001", minimum=50, run_id=run_id)
        self.assertNotEqual(changed["run_id"], run_id)
        different_gate = run_check(self.store, path, "chapter_001", minimum=500, task="检查字数")
        self.assertNotEqual(different_gate["run_id"], changed["run_id"])

    def test_context_is_relevant_and_bounded_after_100_chapters(self):
        facts = []
        for index in range(100):
            facts.append(_make_fact(f"chapter_{index:03d}", f"novel/chapters/chapter_{index:03d}.md", 1, "location", f"人物{index}", "位于", "黑石城" if index == 99 else "远方", 1, "assert", "来源"))
        self.store.commit_facts(facts)
        context = build_context(self.store, "chapter_100", "人物99抵达黑石城", limit=40)
        self.assertLessEqual(len(context.items), 40)
        self.assertEqual(context.items[0].source.chapter, "chapter_099")
        self.assertTrue(context.items[0].reason)

    def test_relationship_update_preserves_history(self):
        first = _make_fact("chapter_001", "novel/chapters/chapter_001.md", 1, "relationship", "沈遥", "关系", "不信任林舟", 4, "assert", "来源")
        self.store.commit_facts([first])
        changed = _make_fact("chapter_002", "novel/chapters/chapter_002.md", 1, "relationship", "沈遥", "关系", "开始信任林舟", 4, "update", "来源")
        self.store.commit_facts([changed])
        facts = self.store.load_facts()
        self.assertEqual(len(facts), 2)
        old = next(fact for fact in facts if fact.fact_id == first.fact_id)
        self.assertEqual(old.status, "historical")
        self.assertEqual(old.history[0]["replaced_by"], changed.fact_id)

    def test_repeating_same_active_fact_keeps_one_record_and_context_state(self):
        first = _make_fact("chapter_001", "novel/chapters/chapter_001.md", 1, "location", "林舟", "location", "黑石城", 5, "assert", "来源")
        second = _make_fact("chapter_002", "novel/chapters/chapter_002.md", 1, "location", "林舟", "location", "黑石城", 5, "assert", "来源")
        self.store.commit_facts([first, second])
        facts = self.store.load_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(len(facts[0].history), 1)
        context = build_context(self.store, "chapter_003", "林舟抵达黑石城")
        self.assertEqual(context.risks, [])
        self.assertEqual(context.state["current_chapter"], 0)

    def test_relationship_change_without_update_is_flagged(self):
        first = _make_fact("chapter_001", "novel/chapters/chapter_001.md", 1, "relationship", "沈遥", "relationship", "不信任林舟", 4, "assert", "来源")
        self.store.commit_facts([first])
        path = chapter(self.root, "chapter_002", "【事实】沈遥|relationship|信任林舟|4\n" + "沈遥点头。" * 30)
        report = run_check(self.store, path, "chapter_002", minimum=50)
        self.assertEqual(report["status"], "带警告通过")
        self.assertTrue(any(issue["code"] == "relationship_transition" for issue in report["issues"]))

    def test_formal_snapshot_change_invalidates_old_run_before_commit(self):
        path = chapter(self.root, "chapter_001", "【事实】林舟|location|黑石城|5\n" + "林舟推门。" * 30)
        first = run_check(self.store, path, "chapter_001", minimum=50)
        self.store.commit_facts([_make_fact("chapter_000", "novel/chapters/chapter_000.md", 1, "world_rule", "城门", "规则", "夜间关闭", 5, "assert", "来源")])
        second = run_check(self.store, path, "chapter_001", minimum=50, run_id=first["run_id"])
        self.assertTrue(second["formal_memory_committed"])
        self.assertIn("world_rule:城门:规则", {fact.state_key for fact in self.store.load_facts()})

    def test_reader_and_ai_symptom_evidence_has_locations(self):
        text = "\n\n".join(["与此同时，他沉默片刻。" * 3 for _ in range(10)]) + "\n\n但他不知道的是，门外有敌人。"
        path = chapter(self.root, "chapter_001", text)
        report = run_check(self.store, path, "chapter_001", minimum=30)
        codes = {issue["code"] for issue in report["issues"]}
        self.assertIn("repeated_expression", codes)
        self.assertTrue(next(issue for issue in report["issues"] if issue["code"] == "repeated_expression")["location"])
        self.assertTrue(report["reader"]["mechanical"].startswith("第"))

    def test_modern_slang_is_a_warning_with_evidence(self):
        path = chapter(self.root, "chapter_001", "林舟说：这波破防了。" * 10)
        report = run_check(self.store, path, "chapter_001", minimum=30)
        slang = [issue for issue in report["issues"] if issue["code"] == "era_slang"]
        self.assertTrue(slang)
        self.assertEqual(slang[0]["severity"], "warning")

    def test_formal_memory_rebuilds_context_after_temporary_indexes_are_deleted(self):
        path = chapter(self.root, "chapter_001", "【事实】林舟|location|黑石城|5\n" + "林舟推门。" * 30)
        report = run_check(self.store, path, "chapter_001", minimum=50)
        self.assertTrue(report["formal_memory_committed"])
        for directory in (self.root / ".book_inspect" / "context", self.root / ".book_inspect" / "runs", self.root / ".book_inspect" / "reports"):
            for item in directory.glob("*"):
                item.unlink()
        restored = build_context(self.store, "chapter_002", "林舟抵达黑石城")
        self.assertTrue(restored.items)
        self.assertEqual(restored.items[0].source.chapter, "chapter_001")


if __name__ == "__main__":
    unittest.main()
