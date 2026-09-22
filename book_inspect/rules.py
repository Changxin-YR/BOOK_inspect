from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .models import Fact, Issue, Source, Stats
from .store import sha256_text

PROTECTED_KINDS = {
    "death", "identity", "world_rule", "secret", "injury", "power",
    "item", "foreshadow", "timeline", "relationship", "location",
}
OVERUSED_WORDS = {
    "然而", "与此同时", "这一刻", "仿佛", "似乎", "不是", "而是",
    "沉默片刻", "瞳孔一缩", "心中一震", "嘴角微扬", "深吸一口气",
}
TEMPLATE_ENDINGS = ("但他不知道的是", "更大的危机还在后面", "一切才刚刚开始")
TRIVIAL_MARKERS = ("吃饭", "喝水", "天气很好", "路人甲")
MODERN_SLANG = ("破防", "YYDS", "CPU", "社死", "打工人", "内卷", "显眼包", "蚌埠住了", "绝绝子")


def _style_text(text: str) -> str:
    return re.sub(r"^\s*【[^】]+】.*$", "", text, flags=re.MULTILINE)


def _location(text: str, needle: str) -> str:
    offset = text.find(needle)
    if offset < 0:
        return ""
    return f"字符{offset + 1}"


def split_paragraphs(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n+", text) if item.strip()]


def split_sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[。！？!?；;])", text) if item.strip()]


def stats(text: str) -> Stats:
    # Structured fact lines are metadata, not prose characters for the chapter gate.
    body = _style_text(text)
    paragraphs = split_paragraphs(body)
    sentences = split_sentences(body)
    sentence_lengths = [len(re.sub(r"\s+", "", sentence)) for sentence in sentences]
    mean = statistics.fmean(sentence_lengths) if sentence_lengths else 0.0
    deviation = statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
    dialogue = sum(len(match.group(1)) for match in re.finditer(r"[“\"]([^”\"]+)[”\"]", body))
    return Stats(
        effective_chars=len(re.sub(r"\s+", "", body)),
        chinese_chars=len(re.findall(r"[\u3400-\u9fff]", body)),
        non_whitespace_chars=len(re.sub(r"\s", "", body)),
        paragraphs=len(paragraphs),
        sentences=len(sentences),
        dialogue_chars=dialogue,
        dialogue_ratio=round(dialogue / max(1, len(re.sub(r"\s+", "", text))), 4),
        sentence_lengths=sentence_lengths,
        mean_sentence_length=round(mean, 2),
        sentence_length_stdev=round(deviation, 2),
    )


def _fact_id(chapter: str, line: int, kind: str, subject: str, predicate: str, value: str) -> str:
    raw = "|".join((chapter, str(line), kind, subject, predicate, value))
    return sha256_text(raw)[:20]


def _make_fact(chapter: str, path: str, line: int, kind: str, subject: str, predicate: str, value: str,
               importance: int = 1, mode: str = "assert", quote: str = "") -> Fact:
    protected = kind in PROTECTED_KINDS or importance >= 5
    tier = "canonical" if protected or importance >= 4 else ("active" if importance >= 2 else "short-term")
    state_key = f"{kind}:{subject}:{predicate}"
    return Fact(
        fact_id=_fact_id(chapter, line, kind, subject, predicate, value),
        state_key=state_key,
        kind=kind,
        subject=subject,
        predicate=predicate,
        value=value,
        tier=tier,
        importance=importance,
        protected=protected,
        source=Source(chapter=chapter, path=path, line=line, quote=quote[:180]),
        mode=mode,
    )


def extract_facts(text: str, chapter: str, path: str) -> list[Fact]:
    """从显式标记和少量稳定句式提取候选事实；普通动作不会进入长期记忆。"""
    # ponytail: deterministic regex keeps offline runs reproducible; ambiguous prose uses the sidecar/model adapter.
    facts: list[Fact] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        marker = re.search(r"【事实】\s*([^|]+)\|([^|]+)\|([^|]+)(?:\|([^|]+))?(?:\|([^|]+))?", stripped)
        if marker:
            subject, predicate, value = (part.strip() for part in marker.group(1, 2, 3))
            importance = int(marker.group(4) or 1) if (marker.group(4) or "").isdigit() else 1
            mode = (marker.group(5) or "assert").strip()
            kind = predicate if predicate in PROTECTED_KINDS else "fact"
            facts.append(_make_fact(chapter, path, line_no, kind, subject, predicate, value, importance, mode, stripped))
            continue
        special = re.search(r"【(伏笔|规则|死亡|身份|伤势|战力|物品|关系|地点|时间|秘密)】\s*([^:：]+)[:：](.+)", stripped)
        if special:
            label, subject, value = special.group(1), special.group(2).strip(), special.group(3).strip()
            kind_map = {"伏笔": "foreshadow", "规则": "world_rule", "死亡": "death", "身份": "identity",
                        "伤势": "injury", "战力": "power", "物品": "item", "关系": "relationship",
                        "地点": "location", "时间": "timeline", "秘密": "secret"}
            kind = kind_map[label]
            facts.append(_make_fact(chapter, path, line_no, kind, subject, label, value, 5 if kind in PROTECTED_KINDS else 3, "assert", stripped))
            continue
        regexes = [
            (r"([\u3400-\u9fff]{2,4})获得([^，。；：:]{1,18})", "item", "获得"),
            (r"([\u3400-\u9fff]{2,4})失去([^，。；：:]{1,18})", "item", "失去"),
            (r"([\u3400-\u9fff]{2,4})(?:在[^，。；：:]{1,8})?抵达([^，。；：:]{1,18})", "location", "位于"),
            (r"([\u3400-\u9fff]{2,4})受伤", "injury", "受伤"),
            (r"([\u3400-\u9fff]{2,4})死亡", "death", "死亡"),
        ]
        for pattern, kind, predicate in regexes:
            match = re.search(pattern, stripped)
            if match:
                subject = match.group(1).strip()
                value = match.group(2).strip() if match.lastindex and match.lastindex > 1 else "严重"
                if any(marker in subject or marker in value for marker in TRIVIAL_MARKERS):
                    continue
                facts.append(_make_fact(chapter, path, line_no, kind, subject, predicate, value, 4 if kind in PROTECTED_KINDS else 2, "assert", stripped))
                break
    return facts


def hard_count_issues(measure: Stats, minimum: int) -> list[Issue]:
    if measure.effective_chars < minimum:
        return [Issue("word_count", "error", f"有效字符 {measure.effective_chars} 低于硬要求 {minimum}，差 {minimum - measure.effective_chars} 字", "stats", blocking=True)]
    if measure.chinese_chars < max(100, int(minimum * 0.25)):
        return [Issue("low_chinese_density", "warning", f"中文字符只有 {measure.chinese_chars}，请确认不是用标点或空白凑字数", "stats")]
    return []


def continuity_issues(candidates: Iterable[Fact], formal: Iterable[Fact], text: str) -> list[Issue]:
    all_facts = list(formal) + list(candidates)
    issues: list[Issue] = []
    grouped: dict[str, list[Fact]] = defaultdict(list)
    for fact in all_facts:
        if fact.status == "active":
            grouped[fact.state_key].append(fact)
    for key, values in grouped.items():
        unique = {item.value for item in values}
        if len(unique) <= 1:
            continue
        latest = values[-1]
        if latest.mode == "update":
            continue
        if latest.kind in {"location", "death", "identity", "power", "injury", "item", "secret", "world_rule"}:
            evidence = [f"{item.source.chapter}:{item.source.line} {item.value}" for item in values[-3:]]
            issues.append(Issue("fact_conflict", "error", f"状态键 {key} 出现无法同时成立的值：{' / '.join(sorted(unique))}", "continuity", evidence=evidence, blocking=True))
        elif latest.kind == "relationship":
            evidence = [f"{item.source.chapter}:{item.source.line} {item.value}" for item in values[-3:]]
            issues.append(Issue("relationship_transition", "warning", f"关系状态 {key} 出现变化，请用 update 明确这是演变而非冲突", "continuity", evidence=evidence))
    explicit = re.search(r"【(连续性冲突|认知穿帮|违反规则|时间线冲突)】\s*(.+)", text)
    if explicit:
        issues.append(Issue("explicit_continuity", "error", explicit.group(2).strip(), "continuity", blocking=True))
    return issues


def foreshadow_issues(candidates: Iterable[Fact], formal: Iterable[Fact]) -> list[Issue]:
    all_facts = list(formal) + list(candidates)
    issues: list[Issue] = []
    for fact in all_facts:
        if fact.kind == "foreshadow" and fact.value.strip() in {"已废弃", "废弃"}:
            issues.append(Issue("foreshadow_discarded", "warning", f"伏笔 {fact.subject} 被标记废弃，需保留原因和替代线索", "foreshadow", f"{fact.source.chapter}:{fact.source.line}"))
    return issues


def _ngrams(text: str, n: int = 4) -> Counter[str]:
    compact = re.sub(r"\s+", "", text)
    return Counter(compact[i:i + n] for i in range(max(0, len(compact) - n + 1)))


def ai_symptom_issues(text: str, history: Iterable[str]) -> list[Issue]:
    issues: list[Issue] = []
    text = _style_text(text)
    compact = re.sub(r"\s+", "", text)
    for word in OVERUSED_WORDS:
        count = compact.count(word)
        if count >= 5 or (len(compact) and count / max(1, len(compact)) > 0.0025):
            issues.append(Issue("repeated_expression", "warning", f"“{word}”出现 {count} 次，结合上下文检查是否形成机械模板", "ai_style", _location(text, word)))
    measure = stats(text)
    if measure.sentences >= 12 and measure.sentence_length_stdev < 4:
        issues.append(Issue("regular_sentence_rhythm", "warning", f"句长标准差仅 {measure.sentence_length_stdev}，节奏可能过于整齐", "ai_style", "全文句长统计"))
    paragraphs = split_paragraphs(text)
    if len(paragraphs) >= 8:
        lengths = [len(re.sub(r"\s+", "", p)) for p in paragraphs]
        if statistics.pstdev(lengths) < 12:
            issues.append(Issue("regular_paragraphs", "warning", "连续段落长度过于接近，可能有模板化分段", "ai_style", "全文段落统计"))
    for ending in TEMPLATE_ENDINGS:
        if compact.endswith(ending) or ending in compact[-80:]:
            issues.append(Issue("template_ending", "warning", f"章末接近模板化悬念：“{ending}”", "ai_style", _location(text, ending)))
    history_text = _style_text("\n".join(history))
    overlap = _ngrams(text).most_common(20)
    repeated = [(gram, count, history_text.count(gram)) for gram, count in overlap if len(gram) >= 4 and history_text.count(gram) >= 2 and count >= 2]
    if repeated:
        gram, count, old_count = max(repeated, key=lambda item: item[1] + item[2])
        issues.append(Issue("cross_chapter_repeat", "warning", f"短语“{gram}”在本章 {count} 次、历史窗口至少 {old_count} 次，需人工判断是否过度复用", "ai_style", _location(text, gram)))
    if re.search(r"动作.{0,16}(心中|内心|感到).{0,18}(震|紧|害怕|愤怒)", text):
        issues.append(Issue("emotion_redundancy", "warning", "动作已经表达情绪，旁白又重复解释同一情绪", "ai_style", "情绪重复模式首次出现处"))
    return issues


def repetition_windows(current: str, history: list[str]) -> dict[str, list[dict[str, int | str]]]:
    """按 3/10/20/50 章窗口给出可复核的短语重复证据。"""
    result: dict[str, list[dict[str, int | str]]] = {}
    current = _style_text(current)
    history = [_style_text(item) for item in history]
    for size in (3, 10, 20, 50):
        window = history[-size:]
        counts: Counter[str] = Counter()
        for chapter_text in window:
            counts.update(_ngrams(chapter_text, 4))
        rows = []
        for phrase, count in counts.most_common(8):
            current_count = current.replace("\n", "").count(phrase)
            if count >= 2 or current_count >= 2:
                rows.append({"phrase": phrase, "history_count": count, "current_count": current_count})
        result[str(size)] = rows[:5]
    return result


def dialogue_issues(text: str) -> list[Issue]:
    speakers: dict[str, list[str]] = defaultdict(list)
    for match in re.finditer(r"(?:^|\n)\s*([^：:\n]{1,12})[：:]\s*([^\n]+)", text):
        speakers[match.group(1)].append(match.group(2))
    if len(speakers) < 2:
        return []
    signatures = {speaker: len(set(re.findall(r"[\u3400-\u9fff]{2,4}", "".join(lines)))) for speaker, lines in speakers.items()}
    if len(set(signatures.values())) == 1 and all(len(lines) >= 2 for lines in speakers.values()):
        return [Issue("uniform_dialogue", "warning", "多个角色对白词汇签名高度相同，检查称呼、礼貌程度和句长差异", "style")]
    return []


def style_issues(text: str, profile: dict) -> list[Issue]:
    issues: list[Issue] = []
    requested = " ".join(str(value) for value in profile.values())
    if any(word in requested for word in ("克制", "细腻")) and re.search(r"直接说出|他很愤怒|她很悲伤", text):
        issues.append(Issue("style_direct_emotion", "warning", "文风档案要求克制或细腻时，出现直接贴标签式情绪说明", "style"))
    if any(word in requested for word in ("快节奏", "推进")) and len(split_paragraphs(text)) > 3:
        if not re.search(r"战|逃|抵达|发现|决定|失去|获得|揭露|冲突", text):
            issues.append(Issue("style_low_motion", "warning", "当前段落缺少可验证事件、目标或信息变化", "plot"))
    return issues


def era_issues(text: str, profile: dict) -> list[Issue]:
    """梗只做时代/语境提示，不把单个词硬判成错误。"""
    if str(profile.get("world_type", "")) == "现代" or profile.get("allow_modern_slang") is True:
        return []
    issues: list[Issue] = []
    for slang in MODERN_SLANG:
        count = text.count(slang)
        if count:
            issues.append(Issue("era_slang", "warning", f"发现现代网络表达“{slang}”{count}次，请核对角色身份、时代和场景语气", "era"))
    return issues


def reader_feedback(text: str) -> dict:
    text = _style_text(text)
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return {"first_skip": "", "first_confusion": "", "first_hook": "", "mechanical": "", "delete_candidates": [], "continue_desire": False}
    skip = next((f"第{i + 1}段：{p[:80]}" for i, p in enumerate(paragraphs) if len(p) > 180 and not re.search(r"[？！!?]", p)), "")
    confusion = next((f"第{i + 1}段：信息密度高但缺少主体或因果：{p[:80]}" for i, p in enumerate(paragraphs) if len(p) > 140 and p.count("因为") + p.count("所谓") >= 2), "")
    hook = next((f"第{i + 1}段：{p[:100]}" for i, p in enumerate(paragraphs) if re.search(r"[？！!?]|战|逃|发现|敲门|血", p)), "")
    mechanical = next((f"第{i + 1}段：{p[:100]}" for i, p in enumerate(paragraphs) if any(word in p for word in ("然而", "与此同时", "这一刻", "仿佛")) and len(p) < 80), "")
    deletes = [f"第{i + 1}段：{p[:100]}" for i, p in enumerate(paragraphs) if (p.count("是") >= 5 and len(p) > 120) or p.endswith(TEMPLATE_ENDINGS)]
    desire = bool(re.search(r"未完|危机|秘密|门|追兵|下一", text[-180:]))
    return {"first_skip": skip, "first_confusion": confusion, "first_hook": hook, "mechanical": mechanical, "delete_candidates": deletes[:3], "continue_desire": desire}


def user_fact_quality(fact: Fact) -> bool:
    return bool(fact.subject and fact.value and not any(marker in fact.value for marker in TRIVIAL_MARKERS))
