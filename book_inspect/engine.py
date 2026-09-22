from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .models import ContextItem, ContextPack, Fact, Issue, RunState, to_dict
from .rules import (
    ai_symptom_issues,
    continuity_issues,
    dialogue_issues,
    era_issues,
    extract_facts,
    foreshadow_issues,
    hard_count_issues,
    reader_feedback,
    repetition_windows,
    stats,
    style_issues,
    user_fact_quality,
)
from .store import ProjectStore, canonical_json, now_iso, safe_id, sha256_text

STAGES = ("stats", "context", "facts", "continuity", "style", "reader", "gate")


def _issue_dict(issue: Issue) -> dict[str, Any]:
    return to_dict(issue)


def _fact_dict(fact: Fact) -> dict[str, Any]:
    return to_dict(fact)


def _path(store: ProjectStore, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else store.root / path


def _chapter_number(chapter: str) -> int:
    match = re.search(r"\d+", chapter)
    return int(match.group(0)) if match else 0


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[\u3400-\u9fff]{2,8}\d{0,3}|[A-Za-z]+\d+", text)
    return [word for word, count in Counter(words).most_common(60) if count >= 1]


def build_context(store: ProjectStore, chapter: str, text: str = "", task: str = "检查或续写当前章节", limit: int | None = None) -> ContextPack:
    store.init()
    config = store.load_config()
    limit = limit or int(config.get("context_limit", 40))
    keywords = set(_keywords(text))
    facts = store.load_facts()
    scored: list[ContextItem] = []
    # ponytail: linear scan is predictable for a Git-sized project; add an index only after profiling says it matters.
    for fact in facts:
        if fact.status == "historical" and not fact.protected:
            base = 0.0
        else:
            base = float(fact.importance * 2)
        hits = [term for term in keywords if term in (fact.subject + fact.predicate + fact.value)]
        reasons: list[str] = []
        if hits:
            base += 20 + len(hits) * 2
            reasons.append(f"与当前文本实体/关键词相关：{'、'.join(hits[:4])}")
        if fact.protected:
            base += 30
            reasons.append("受保护事实，不能因相似度低而丢失")
        if fact.tier == "active":
            base += 8
            reasons.append("当前活跃记忆")
        if fact.kind in {"foreshadow", "secret", "world_rule", "timeline"}:
            base += 10
            reasons.append("属于剧情线程、伏笔或硬规则")
        if fact.source.chapter == chapter:
            base += 18
            reasons.append("来自当前章节")
        if base > 0:
            scored.append(ContextItem(
                fact_id=fact.fact_id,
                text=f"{fact.subject}：{fact.predicate}={fact.value}",
                reason="；".join(reasons) or "属于正式记忆候选",
                score=round(base, 2),
                source=fact.source,
            ))
    scored.sort(key=lambda item: (-item.score, item.fact_id))
    index = store.load_chapter_index()
    recent = [entry.get("path", "") for entry in index[-int(config.get("recent_chapters", 3)):]]
    risks = [
        f"{fact.state_key}：{fact.value}"
        for fact in facts
        if fact.status == "conflict" or fact.state_key.startswith(("location:", "secret:", "death:")) and fact.protected
    ][:12]
    return ContextPack(task=task, chapter=chapter, items=scored[:limit], recent_chapters=recent, risks=risks, style=store.load_style())


def _load_sidecar_facts(store: ProjectStore, chapter_path: Path, chapter: str) -> list[Fact]:
    sidecar = chapter_path.with_suffix(".facts.json")
    if not sidecar.exists():
        return []
    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    result: list[Fact] = []
    for index, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict) or not item.get("subject") or not item.get("value"):
            continue
        kind = str(item.get("kind", item.get("predicate", "fact")))
        predicate = str(item.get("predicate", kind))
        value = str(item["value"])
        from .rules import _make_fact  # local import keeps the public surface small
        result.append(_make_fact(chapter, str(sidecar.relative_to(store.root)), int(item.get("line", index + 1)), kind,
                                 str(item["subject"]), predicate, value, int(item.get("importance", 1)), str(item.get("mode", "assert")), str(item.get("quote", ""))))
    return result


def _stage(run: dict[str, Any], name: str, value: Any) -> None:
    run["results"][name] = value
    if name not in run["completed"]:
        run["completed"].append(name)
    run["stage"] = name
    run["updated_at"] = now_iso()


def _state_after(store: ProjectStore, chapter: str, facts: list[Fact], run_id: str) -> dict[str, Any]:
    state = dict(store.load_state())
    state["current_chapter"] = max(int(state.get("current_chapter", 0) or 0), _chapter_number(chapter))
    state["last_formal_run"] = run_id
    characters = dict(state.get("characters", {}))
    items = dict(state.get("items", {}))
    relationships = list(state.get("relationships", []))
    threads = list(state.get("threads", []))
    foreshadows = list(state.get("foreshadows", []))
    secrets = list(state.get("known_secrets", []))
    for fact in facts:
        if fact.kind in {"location", "injury", "power", "death", "identity"}:
            entry = dict(characters.get(fact.subject, {}))
            entry[fact.predicate] = fact.value
            entry["source"] = to_dict(fact.source)
            characters[fact.subject] = entry
        elif fact.kind == "item":
            items[fact.subject] = {"value": fact.value, "source": to_dict(fact.source)}
        elif fact.kind == "relationship":
            relationships.append({"subject": fact.subject, "value": fact.value, "source": to_dict(fact.source), "fact_id": fact.fact_id})
        elif fact.kind == "foreshadow":
            foreshadows.append({"subject": fact.subject, "value": fact.value, "status": "active", "source": to_dict(fact.source), "fact_id": fact.fact_id})
            threads.append({"name": fact.subject, "status": "open", "source": to_dict(fact.source)})
        elif fact.kind == "secret":
            secrets.append({"subject": fact.subject, "value": fact.value, "source": to_dict(fact.source), "fact_id": fact.fact_id})
        elif fact.kind == "timeline":
            state["story_time"] = fact.value
    state["characters"] = characters
    state["items"] = items
    state["relationships"] = relationships[-100:]
    state["threads"] = threads[-100:]
    state["foreshadows"] = foreshadows[-100:]
    state["known_secrets"] = secrets[-100:]
    return state


def _handoff(store: ProjectStore, run: dict[str, Any], report: dict[str, Any]) -> None:
    status = report.get("status", "running")
    next_step = "长期记忆已经正式写入，可继续下一章" if report.get("formal_memory_committed") else "修复阻止项后重新运行终审"
    lines = [
        f"当前正式写到第{store.load_state().get('current_chapter', 0)}章。",
        f"正在处理{run['chapter']}。",
        f"本次运行状态：{status}。",
        f"已完成阶段：{'、'.join(run.get('completed', [])) or '无'}。",
        f"下一步：{next_step}。",
        f"运行标识：{run['run_id']}。",
    ]
    store.path("HANDOFF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_check(store: ProjectStore, chapter_path: str | Path, chapter: str | None = None,
              minimum: int | None = None, run_id: str | None = None,
              stop_after: str | None = None, task: str = "检查当前章节") -> dict[str, Any]:
    store.init()
    path = _path(store, chapter_path)
    text = path.read_text(encoding="utf-8")
    chapter = chapter or path.stem
    config = store.load_config()
    minimum = int(minimum if minimum is not None else config.get("min_effective_chars", 4000))
    input_hash = sha256_text(canonical_json({"chapter": chapter, "text": text, "style": store.load_style(), "config": config}))
    formal_hash = store.formal_snapshot_hash()
    run_id = run_id or f"{safe_id(chapter)}-{input_hash[:12]}"
    old = store.load_run(run_id)
    if old and old.get("input_hash") != input_hash:
        run_id = f"{safe_id(chapter)}-{input_hash[:12]}"
        old = store.load_run(run_id)
    run = old or {"run_id": run_id, "chapter": chapter, "chapter_path": str(path.relative_to(store.root)), "input_hash": input_hash, "formal_hash": formal_hash,
                  "stage": "created", "completed": [], "results": {}, "status": "running", "formal_memory_committed": False,
                  "created_at": now_iso(), "updated_at": now_iso()}
    if run.get("input_hash") != input_hash:
        run["input_hash"] = input_hash
        run["formal_hash"] = formal_hash
        run["completed"] = []
        run["results"] = {}
    elif run.get("formal_hash") != formal_hash:
        run["formal_hash"] = formal_hash
        run["completed"] = [stage for stage in run["completed"] if stage in {"stats", "facts", "style", "reader"}]
        for stage in ("context", "continuity", "gate"):
            run["results"].pop(stage, None)
    formal = store.load_facts()
    history_text: list[str] = []
    for entry in store.load_chapter_index()[-20:]:
        old_path = _path(store, entry.get("path", ""))
        if old_path.exists():
            history_text.append(old_path.read_text(encoding="utf-8"))
    def save_and_stop(name: str) -> None:
        store.save_run(run)
        if stop_after == name:
            raise InterruptedError(f"simulated interruption after {name}")

    if "stats" not in run["completed"]:
        _stage(run, "stats", to_dict(stats(text)))
    save_and_stop("stats")
    if "context" not in run["completed"]:
        context = build_context(store, chapter, text, task, int(config.get("context_limit", 40)))
        _stage(run, "context", to_dict(context))
        store.save_context(chapter, to_dict(context))
    save_and_stop("context")
    if "facts" not in run["completed"]:
        extracted = extract_facts(text, chapter, str(path.relative_to(store.root)))
        rejected = [{"quote": fact.source.quote, "reason": "缺少可追溯主体和值，或命中无后续价值的日常标记"} for fact in extracted if not user_fact_quality(fact)]
        facts = [fact for fact in extracted if user_fact_quality(fact)]
        facts.extend(_load_sidecar_facts(store, path, chapter))
        unique = {fact.fact_id: fact for fact in facts}
        _stage(run, "facts", list(unique.values()) and [_fact_dict(item) for item in unique.values()] or [])
        run["results"]["rejected_facts"] = rejected
    save_and_stop("facts")
    from .models import fact_from
    candidates = [fact_from(item) for item in run["results"].get("facts", [])]
    if "continuity" not in run["completed"]:
        issues = continuity_issues(candidates, formal, text) + foreshadow_issues(candidates, formal)
        _stage(run, "continuity", [_issue_dict(item) for item in issues])
    save_and_stop("continuity")
    if "style" not in run["completed"]:
        measure = stats(text)
        profile = store.load_style()
        issues = hard_count_issues(measure, minimum) + ai_symptom_issues(text, history_text) + dialogue_issues(text) + style_issues(text, profile) + era_issues(text, profile)
        _stage(run, "style", [_issue_dict(item) for item in issues])
        run["results"]["repetition_windows"] = repetition_windows(text, history_text)
    save_and_stop("style")
    if "reader" not in run["completed"]:
        _stage(run, "reader", reader_feedback(text))
    save_and_stop("reader")
    if "gate" not in run["completed"]:
        raw_issues = [*run["results"].get("continuity", []), *run["results"].get("style", [])]
        blocking = [item for item in raw_issues if item.get("blocking") or item.get("severity") == "error"]
        status = "阻止发布" if blocking else ("带警告通过" if raw_issues else "通过")
        _stage(run, "gate", {"status": status, "issues": raw_issues})
    gate = run["results"]["gate"]
    status = gate["status"]
    if status != "阻止发布" and not run.get("formal_memory_committed"):
        committed = store.commit_facts(candidates)
        state = _state_after(store, chapter, committed, run_id)
        store.save_state(state)
        run["formal_memory_committed"] = True
        run["results"]["committed_fact_ids"] = [fact.fact_id for fact in committed]
        run["updated_at"] = now_iso()
        entries = [entry for entry in store.load_chapter_index() if entry.get("chapter") != chapter]
        entries.append({"chapter": chapter, "path": str(path.relative_to(store.root)), "input_hash": input_hash,
                        "status": status, "run_id": run_id, "stats": run["results"]["stats"], "fact_ids": run["results"].get("committed_fact_ids", [])})
        entries.sort(key=lambda item: (_chapter_number(str(item.get("chapter", ""))), str(item.get("chapter", ""))))
        store.save_chapter_index(entries)
    run["status"] = status
    report = {"run_id": run_id, "chapter": chapter, "chapter_path": str(path.relative_to(store.root)), "input_hash": input_hash,
              "status": status, "stats": run["results"]["stats"], "context": run["results"].get("context", {}),
              "facts": run["results"].get("facts", []), "issues": gate["issues"], "reader": run["results"].get("reader", {}),
              "formal_memory_committed": run.get("formal_memory_committed", False),
              "completed_stages": run["completed"], "evidence": {"memory_ids": [item.get("fact_id") for item in run["results"].get("context", {}).get("items", [])],
              "repetition_windows": run["results"].get("repetition_windows", {}),
              "rejected_candidates": run["results"].get("rejected_facts", [])}}
    store.save_run(run)
    store.save_report(chapter, report)
    _handoff(store, run, report)
    return report


def restore_context(store: ProjectStore, chapter_path: str | Path, task: str = "继续之前的任务") -> dict[str, Any]:
    store.init()
    path = _path(store, chapter_path)
    chapter = path.stem
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    context = build_context(store, chapter, text, task)
    return to_dict(context)
