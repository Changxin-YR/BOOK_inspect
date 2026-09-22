from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import Fact, RunState, fact_from, to_dict


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


def safe_id(value: str) -> str:
    return re.sub(r"[^\w\-]+", "-", value, flags=re.UNICODE).strip("-") or "item"


class ProjectStore:
    """Git 友好的小说项目存储；正式数据和运行候选数据分开。"""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.meta_dir = self.root / ".book_inspect"
        self.memory_dir = self.meta_dir / "memory"
        self.runs_dir = self.meta_dir / "runs"
        self.reports_dir = self.meta_dir / "reports"
        self.context_dir = self.meta_dir / "context"
        self.chapters_dir = self.root / "novel" / "chapters"

    def init(self) -> None:
        for directory in (self.meta_dir, self.memory_dir, self.runs_dir, self.reports_dir, self.context_dir, self.chapters_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.path("config.json").exists():
            self.write_json("config.json", {
                "min_effective_chars": 4000,
                "context_limit": 40,
                "recent_chapters": 3,
                "style_profile": "style.json",
                "world_rules": [],
            })
        if not self.path("style.json").exists():
            self.write_json("style.json", {
                "tone": ["有画面感", "人物差异明显"],
                "pace": "每章产生可验证变化",
                "narrator_distance": "随视角人物变化",
                "dialogue_density": "按场景需要",
                "emotion": "优先通过行为和选择呈现",
                "modern_slang": "仅在世界观和角色身份允许时使用",
                "reader_profile": "目标题材核心读者：快速判断冲突、角色记忆点和下一章欲望",
            })
        if not self.path("memory/facts.json").exists():
            self.write_json("memory/facts.json", [])
        if not self.path("memory/state.json").exists():
            self.write_json("memory/state.json", {
                "current_chapter": 0,
                "story_time": "",
                "characters": {},
                "relationships": [],
                "items": {},
                "threads": [],
                "foreshadows": [],
                "known_secrets": [],
                "last_formal_run": "",
                "state_hash": "",
            })
        if not self.path("memory/foreshadows.json").exists():
            self.write_json("memory/foreshadows.json", [])
        if not self.path("memory/chapters.json").exists():
            self.write_json("memory/chapters.json", [])

    def path(self, relative: str | Path) -> Path:
        return self.meta_dir / relative

    def write_json(self, relative: str | Path, value: Any) -> None:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def read_json(self, relative: str | Path, default: Any = None) -> Any:
        path = self.path(relative)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def load_config(self) -> dict[str, Any]:
        self.init()
        return self.read_json("config.json", {})

    def load_style(self) -> dict[str, Any]:
        config = self.load_config()
        return self.read_json(str(config.get("style_profile", "style.json")), {})

    def load_facts(self) -> list[Fact]:
        return [fact_from(item) for item in self.read_json("memory/facts.json", [])]

    def save_facts(self, facts: Iterable[Fact]) -> None:
        self.write_json("memory/facts.json", [to_dict(item) for item in facts])

    def commit_facts(self, candidates: Iterable[Fact]) -> list[Fact]:
        """按 fact_id 幂等写入，状态变化追加 history，旧值不删除。"""
        current = self.load_facts()
        by_id = {item.fact_id: item for item in current}
        committed: list[Fact] = []
        for candidate in candidates:
            previous = by_id.get(candidate.fact_id)
            if previous:
                committed.append(previous)
                continue
            same_key = [item for item in current if item.state_key == candidate.state_key and item.status == "active"]
            same_value = next((item for item in same_key if item.value == candidate.value), None)
            if same_value:
                same_value.history.append({"seen_at": now_iso(), "source": to_dict(candidate.source)})
                committed.append(same_value)
                continue
            if same_key and candidate.mode == "update":
                for old in same_key:
                    old.status = "historical"
                    old.history.append({"changed_at": now_iso(), "replaced_by": candidate.fact_id, "value": old.value})
            current.append(candidate)
            by_id[candidate.fact_id] = candidate
            committed.append(candidate)
        self.save_facts(current)
        return committed

    def load_state(self) -> dict[str, Any]:
        return self.read_json("memory/state.json", {})

    def save_state(self, state: dict[str, Any]) -> None:
        state = dict(state)
        state["state_hash"] = sha256_text(canonical_json({k: v for k, v in state.items() if k != "state_hash"}))
        self.write_json("memory/state.json", state)

    def load_chapter_index(self) -> list[dict[str, Any]]:
        return self.read_json("memory/chapters.json", [])

    def save_chapter_index(self, entries: list[dict[str, Any]]) -> None:
        self.write_json("memory/chapters.json", entries)

    def save_run(self, run: RunState | dict[str, Any]) -> None:
        payload = to_dict(run) if isinstance(run, RunState) else run
        self.write_json(Path("runs") / f"{safe_id(payload['run_id'])}.json", payload)

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        return self.read_json(Path("runs") / f"{safe_id(run_id)}.json")

    def save_report(self, chapter: str, report: dict[str, Any]) -> Path:
        path = self.reports_dir / f"{safe_id(chapter)}.json"
        relative = path.relative_to(self.meta_dir)
        self.write_json(relative, report)
        return path

    def save_context(self, chapter: str, context: dict[str, Any]) -> Path:
        path = self.context_dir / f"{safe_id(chapter)}.json"
        relative = path.relative_to(self.meta_dir)
        self.write_json(relative, context)
        return path

    def formal_snapshot_hash(self) -> str:
        state = self.load_state()
        facts = [to_dict(item) for item in self.load_facts()]
        return sha256_text(canonical_json({"state": state, "facts": facts}))
