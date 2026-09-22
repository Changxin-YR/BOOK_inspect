from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Source:
    chapter: str
    path: str
    line: int = 0
    quote: str = ""


@dataclass
class Fact:
    fact_id: str
    state_key: str
    kind: str
    subject: str
    predicate: str
    value: str
    tier: str = "active"
    importance: int = 1
    protected: bool = False
    status: str = "active"
    source: Source = field(default_factory=lambda: Source("", ""))
    mode: str = "assert"
    related: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    phase: str
    location: str = ""
    evidence: list[str] = field(default_factory=list)
    blocking: bool = False


@dataclass
class Stats:
    effective_chars: int
    chinese_chars: int
    non_whitespace_chars: int
    paragraphs: int
    sentences: int
    dialogue_chars: int
    dialogue_ratio: float
    sentence_lengths: list[int]
    mean_sentence_length: float
    sentence_length_stdev: float


@dataclass
class ContextItem:
    fact_id: str
    text: str
    reason: str
    score: float
    source: Source


@dataclass
class ContextPack:
    task: str
    chapter: str
    items: list[ContextItem] = field(default_factory=list)
    recent_chapters: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    style: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunState:
    run_id: str
    chapter: str
    chapter_path: str
    input_hash: str
    stage: str = "created"
    completed: list[str] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    formal_memory_committed: bool = False
    created_at: str = ""
    updated_at: str = ""


def to_dict(value: Any) -> Any:
    """把 dataclass 嵌套结构转换成可写入 JSON 的普通对象。"""
    if hasattr(value, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [to_dict(v) for v in value]
    if isinstance(value, dict):
        return {k: to_dict(v) for k, v in value.items()}
    return value


def source_from(value: dict[str, Any]) -> Source:
    return Source(
        chapter=str(value.get("chapter", "")),
        path=str(value.get("path", "")),
        line=int(value.get("line", 0) or 0),
        quote=str(value.get("quote", "")),
    )


def fact_from(value: dict[str, Any]) -> Fact:
    return Fact(
        fact_id=str(value["fact_id"]),
        state_key=str(value.get("state_key", "")),
        kind=str(value.get("kind", "fact")),
        subject=str(value.get("subject", "")),
        predicate=str(value.get("predicate", "")),
        value=str(value.get("value", "")),
        tier=str(value.get("tier", "active")),
        importance=int(value.get("importance", 1) or 1),
        protected=bool(value.get("protected", False)),
        status=str(value.get("status", "active")),
        source=source_from(value.get("source", {})),
        mode=str(value.get("mode", "assert")),
        related=list(value.get("related", [])),
        history=list(value.get("history", [])),
    )
