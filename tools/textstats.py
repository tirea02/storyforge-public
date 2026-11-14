"""원고 텍스트 분석: 글자 수, 서식 위생, 문단 호흡, 문체 패턴.

대사 기호는 작품마다 다르므로 Notation(작품 설정의 notation)을 받아서 판단한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from tools.project import Notation

# 눈에 보이지 않거나 업로드 시 문제를 일으키는 문자
INVISIBLE_NAMES: dict[str, str] = {
    "​": "폭 없는 공백(U+200B)",
    "‌": "폭 없는 비결합자(U+200C)",
    "‍": "폭 없는 결합자(U+200D)",
    "﻿": "BOM/폭 없는 줄바꿈 금지(U+FEFF)",
    " ": "줄바꿈 없는 공백(NBSP, U+00A0)",
    "　": "전각 공백(U+3000)",
}

DEFAULT_NOTATION = Notation()


@dataclass
class LengthReport:
    no_space: int
    with_space: int
    muble_estimate: int


@dataclass
class Issue:
    kind: str
    message: str
    lines: list[int] = field(default_factory=list)

    def render(self, max_lines: int = 12) -> str:
        if not self.lines:
            return f"- [{self.kind}] {self.message}"
        shown = ", ".join(str(n) for n in self.lines[:max_lines])
        more = f" 외 {len(self.lines) - max_lines}곳" if len(self.lines) > max_lines else ""
        return f"- [{self.kind}] {self.message} → {shown}행{more}"


@dataclass
class ParagraphStats:
    paragraphs: int
    narration: int
    narration_avg_len: float
    narration_multi_sentence: int
    narration_short_ratio: float


@dataclass
class PatternHit:
    pattern_id: str
    label: str
    count: int
    limit: int | None
    lines: list[int]
    advice: str

    @property
    def over(self) -> bool:
        return self.limit is not None and self.count > self.limit


def count_length(text: str, muble_ratio: float = 1.0) -> LengthReport:
    """공백 제외/포함 글자 수와 뮤블 기준 추정치."""
    no_space = len("".join(text.split()))
    with_space = len(text.replace("\n", ""))
    return LengthReport(no_space=no_space, with_space=with_space, muble_estimate=round(no_space * muble_ratio))


def hygiene_issues(text: str) -> list[Issue]:
    """업로드 전에 정리해야 할 서식 문제를 찾는다."""
    issues: list[Issue] = []
    lines = text.split("\n")

    for ch, name in INVISIBLE_NAMES.items():
        hit = [i for i, line in enumerate(lines, 1) if ch in line]
        if hit:
            issues.append(Issue("보이지 않는 문자", f"{name} {text.count(ch)}개", hit))
    def suspicious(c: str) -> str | None:
        """기본 목록 밖의 보이지 않거나 업로드에 문제를 일으키는 문자 종류."""
        if c in INVISIBLE_NAMES or c in "\n\t ":
            return None
        cat = unicodedata.category(c)
        code = ord(c)
        if cat == "Cf":
            return "서식 문자"
        if cat == "Cc":
            return "제어 문자"
        if cat in ("Zs", "Zl", "Zp"):
            return "특수 공백·구분 문자"
        if 0xE000 <= code <= 0xF8FF:
            return "사용자 정의 문자(PUA)"
        if 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF:
            return "변형 선택자"
        return None

    for ch in sorted({c for c in text if suspicious(c)}):
        hit = [i for i, line in enumerate(lines, 1) if ch in line]
        name = unicodedata.name(ch, "?")
        issues.append(Issue("보이지 않는 문자", f"{suspicious(ch)} U+{ord(ch):04X} {name} {text.count(ch)}개", hit))

    checks: list[tuple[str, str, Callable[[str], bool]]] = [
        ("줄 앞 공백", "줄 앞에 공백/탭", lambda l: l != "" and l[0] in " \t"),
        ("줄 끝 공백", "줄 끝에 공백/탭", lambda l: l.strip() != "" and l[-1] in " \t"),
        ("공백만 있는 줄", "빈 줄처럼 보이지만 공백이 들어 있음", lambda l: l != "" and l.strip() == ""),
        ("이중 공백", "문장 안에 연속 공백", lambda l: "  " in l.strip()),
        ("탭 문자", "탭 문자", lambda l: "\t" in l.strip()),
    ]
    for kind, msg, pred in checks:
        hit = [i for i, line in enumerate(lines, 1) if pred(line)]
        if hit:
            issues.append(Issue(kind, msg, hit))
    return issues


def quote_issues(text: str, notation: Notation = DEFAULT_NOTATION) -> list[Issue]:
    """한 줄 안에서 대사 기호 짝이 맞지 않는 줄(작품 notation 기준)."""
    issues: list[Issue] = []
    lines = text.split("\n")
    for name, o, c in notation.asymmetric_pairs():
        bad = [i for i, l in enumerate(lines, 1) if l.count(o) != l.count(c)]
        if bad:
            issues.append(Issue(f"{name} 기호 짝", f"{o} {c} 개수가 맞지 않음", bad))
    for name, mark in notation.symmetric_marks():
        bad = [i for i, l in enumerate(lines, 1) if l.count(mark) % 2 == 1]
        if bad:
            issues.append(Issue(f"{name} 기호 짝", f"{mark} 개수가 홀수", bad))
    return issues


STRAIGHT_TO_CURLY = {"'": "‘’", '"': "“”"}


def quote_style_issues(text: str, notation: Notation = DEFAULT_NOTATION) -> list[Issue]:
    """작품이 쓰는 따옴표 모양(곧은 ' " / 둥근 ‘’ “”)과 다른 모양이 섞인 줄.

    플랫폼 편집기에서 직접 고친 문장만 둥근 따옴표로 바뀌는 경우를 잡는다.
    """
    used = {o for o, _ in notation.pairs.values()} | {c for _, c in notation.pairs.values()}
    issues: list[Issue] = []
    lines = text.split("\n")
    for straight, curly in STRAIGHT_TO_CURLY.items():
        if straight in used:
            foreign, expected = curly, straight
        elif curly[0] in used:
            foreign, expected = straight, curly
        else:
            continue
        hit = [i for i, l in enumerate(lines, 1) if any(ch in l for ch in foreign)]
        if hit:
            issues.append(Issue("따옴표 모양", f"'{foreign}' 사용 — 작품 표기는 '{expected}'", hit))
    return issues


AUTHOR_NOTE_RE = re.compile(r"[()（）]|(?:^|\s)or\s*$")


def author_note_issues(text: str) -> list[Issue]:
    """원고에 남은 작가 메모 의심 줄: 괄호, 줄 끝 'or'(대안 나열).

    작가가 원고 안에 괄호로 질문·대안을 적어 두는 습관이 있어서, 정리 후 남은 메모를 잡는다.
    """
    hit = [i for i, l in enumerate(text.split("\n"), 1) if AUTHOR_NOTE_RE.search(l)]
    return [Issue("메모 의심", "괄호나 'or'가 남은 줄 — 작가 메모면 지우고 답은 따로", hit)] if hit else []


def split_paragraphs(text: str) -> list[tuple[int, str]]:
    """(줄 번호, 문단) 목록. 원고는 한 줄 = 한 문단."""
    return [(i, l.strip()) for i, l in enumerate(text.split("\n"), 1) if l.strip()]


def is_dialogue(paragraph: str, notation: Notation = DEFAULT_NOTATION) -> bool:
    """대사·속말·특수 대사 줄인지. 인용으로 시작하는 서술('밥'한테 …)은 제외."""
    if any(paragraph.startswith(p) for p in notation.line_prefixes):
        return True
    for o, c in notation.pairs.values():
        if paragraph.startswith(o):
            body = paragraph.rstrip()
            return body.endswith(c) or body.endswith(c + ".")
    return False


def sentence_count(paragraph: str) -> int:
    return len(re.findall(r"[.?!…](?=\s|$)", paragraph)) or 1


def paragraph_stats(text: str, notation: Notation = DEFAULT_NOTATION) -> ParagraphStats:
    paras = split_paragraphs(text)
    narr = [p for _, p in paras if not is_dialogue(p, notation)]
    if not narr:
        return ParagraphStats(len(paras), 0, 0.0, 0, 0.0)
    avg = sum(len(p) for p in narr) / len(narr)
    multi = sum(1 for p in narr if sentence_count(p) >= 3)
    short = sum(1 for p in narr if len(p.replace(" ", "")) <= 10)
    return ParagraphStats(
        paragraphs=len(paras),
        narration=len(narr),
        narration_avg_len=round(avg, 1),
        narration_multi_sentence=multi,
        narration_short_ratio=round(short / len(narr), 3),
    )


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def pattern_hits(text: str, patterns: list[dict[str, Any]]) -> list[PatternHit]:
    """패턴(정규식)을 원고에 적용한다.

    패턴 항목: id, label, regex, limit(없으면 정보용), advice, multiline(선택)
    """
    hits: list[PatternHit] = []
    for p in patterns:
        flags = re.MULTILINE
        if p.get("multiline"):
            flags |= re.DOTALL
        rx = re.compile(p["regex"], flags)
        lines = [_line_of(text, m.start()) for m in rx.finditer(text)]
        hits.append(
            PatternHit(
                pattern_id=p["id"],
                label=p.get("label", p["id"]),
                count=len(lines),
                limit=p.get("limit"),
                lines=lines,
                advice=p.get("advice", ""),
            )
        )
    return hits


def rhetorical_triplets(text: str, notation: Notation = DEFAULT_NOTATION, max_len: int = 25) -> list[int]:
    """짧은 의문문 서술 문단이 3개 이상 연달아 나오는 지점(셋 나열 리듬)."""
    found: list[int] = []
    run: list[int] = []
    for line_no, p in split_paragraphs(text):
        if not is_dialogue(p, notation) and p.endswith("?") and len(p) <= max_len:
            run.append(line_no)
        else:
            if len(run) >= 3:
                found.append(run[0])
            run = []
    if len(run) >= 3:
        found.append(run[0])
    return found


SENTENCE_RX = re.compile(r"[^.?!…]+(?:[.?!…]+[\"'』]?|$)")


@dataclass
class ShortRun:
    """짧은 단문이 몰린 구간."""

    start_line: int
    end_line: int
    short: int
    sentences: int
    preview: str


@dataclass
class ShortSentenceReport:
    sentences: int
    short: int
    runs: list[ShortRun]
    max_len: int
    limit: int | None

    @property
    def ratio(self) -> float:
        return round(self.short / self.sentences, 3) if self.sentences else 0.0

    @property
    def over(self) -> bool:
        return self.limit is not None and len(self.runs) > self.limit


def narration_sentences(text: str, notation: Notation = DEFAULT_NOTATION) -> list[tuple[int, str] | None]:
    """서술 문장 목록 (줄 번호, 문장). 대사 줄은 건너뛰고, 장면 전환 표시는 None(구간 끊기)."""
    out: list[tuple[int, str] | None] = []
    for line_no, p in split_paragraphs(text):
        if SCENE_MARK_RX.match(p):
            out.append(None)
            continue
        if is_dialogue(p, notation):
            continue
        out.extend((line_no, s.strip()) for s in SENTENCE_RX.findall(p) if s.strip())
    return out


def short_sentence_runs(
    text: str,
    notation: Notation = DEFAULT_NOTATION,
    max_len: int = 12,
    window: int = 5,
    min_short: int = 4,
    limit: int | None = None,
) -> ShortSentenceReport:
    """짧은 단문(공백 제외 max_len자 이하)이 몰린 구간.

    서술 문장 window개 중 min_short개 이상이 짧으면 그 구간을 표시하고, 겹치는 구간은 합친다.
    대사는 세지 않고 건너뛴다(대사가 끼어도 서술의 단문 리듬은 이어진다). 장면 전환에서 끊는다.
    """
    seq = narration_sentences(text, notation)
    sents = [s for s in seq if s is not None]
    is_short = [s is not None and len(s[1].replace(" ", "")) <= max_len for s in seq]
    spans: list[list[int]] = []
    for i in range(len(seq) - window + 1):
        if any(s is None for s in seq[i : i + window]) or sum(is_short[i : i + window]) < min_short:
            continue
        if spans and i <= spans[-1][1]:
            spans[-1][1] = i + window
        else:
            spans.append([i, i + window])
    runs: list[ShortRun] = []
    for a, b in spans:
        part = [s for s in seq[a:b] if s is not None]
        shorts = [t for (_, t), flag in zip(part, is_short[a:b]) if flag]
        runs.append(ShortRun(part[0][0], part[-1][0], len(shorts), len(part), " / ".join(shorts[:6])))
    return ShortSentenceReport(len(sents), sum(is_short), runs, max_len, limit)


def spacing_suspects(text: str, words: list[str]) -> list[Issue]:
    """자주 틀리는 붙여쓰기 후보(정확한 맞춤법 검사가 아니라 의심 목록)."""
    issues: list[Issue] = []
    lines = text.split("\n")
    for w in words:
        hit = [i for i, l in enumerate(lines, 1) if w in l]
        if hit:
            issues.append(Issue("띄어쓰기 의심", f"'{w}'", hit))
    return issues


ELLIPSIS_STYLES: dict[str, str] = {"……": r"…{2,}", "…": r"(?<!…)…(?!…)", "...": r"\.{3,}", "‥": r"‥+"}


def ellipsis_usage(text: str) -> dict[str, list[int]]:
    """줄임표 표기별 사용 줄 번호. ('……' 2개 이상 묶음 / '…' 단독 / '...' 마침표 / '‥')"""
    lines = text.split("\n")
    usage: dict[str, list[int]] = {}
    for style, rx in ELLIPSIS_STYLES.items():
        hit = [i for i, l in enumerate(lines, 1) if re.search(rx, l)]
        if hit:
            usage[style] = hit
    return usage


def ellipsis_issues(text: str, preferred: str | None = None) -> list[Issue]:
    """줄임표 표기가 섞였거나, 작품이 정한 표기(preferred)와 다른 곳."""
    usage = ellipsis_usage(text)
    if preferred:
        return [
            Issue("줄임표 표기", f"'{style}' 사용 (작품 표기: '{preferred}')", lines)
            for style, lines in usage.items()
            if style != preferred
        ]
    if len(usage) <= 1:
        return []
    main = max(usage, key=lambda s: len(usage[s]))
    return [
        Issue("줄임표 표기", f"'{style}' 사용 — 이 회차는 주로 '{main}'", lines)
        for style, lines in usage.items()
        if style != main
    ]


SCENE_MARK_RX = re.compile(r"^\s*([*＊]{3,}|[-─━=]{3,}|[◇◆○●□■☆★♢◈]+(\s*[◇◆○●□■☆★♢◈])*|#{3,}|~{3,}|[*＊](\s+[*＊]){2,})\s*$")


def _blank_runs(lines: list[str]) -> list[tuple[int, int]]:
    """(시작 줄, 길이) 목록. 파일 끝의 빈 줄은 제외."""
    runs: list[tuple[int, int]] = []
    start, length = 0, 0
    for i, l in enumerate(lines, 1):
        if l.strip() == "":
            if length == 0:
                start = i
            length += 1
        else:
            if length:
                runs.append((start, length))
            length = 0
    return runs


def scene_break_issues(
    text: str, marker: str | None, breath: int | None = None, max_breaths: int = 6
) -> list[Issue]:
    """장면 전환·호흡 표기 검사(작품이 marker를 정한 경우).

    빈 줄 1개 = 기본, breath개 = 같은 장면 안 호흡(허용), 그 밖의 연속 빈 줄 = 경고.
    전환 기호 앞뒤는 빈 줄 1개. 다른 전환 기호 사용도 경고.
    """
    if not marker:
        return []
    lines = text.split("\n")
    issues: list[Issue] = []
    marker_lines = {i for i, l in enumerate(lines, 1) if l.strip() == marker}
    odd: list[int] = []
    around_marker: list[int] = []
    breaths: list[int] = []
    for start, length in _blank_runs(lines):
        end = start + length - 1
        if (start - 1) in marker_lines or (end + 1) in marker_lines:
            if length > 1:
                around_marker.append(start)
        elif length == 1:
            continue
        elif breath and length == breath:
            breaths.append(start)
        else:
            odd.append(start)
    if odd:
        rule = f"호흡은 빈 줄 {breath}개, " if breath else ""
        issues.append(Issue("장면 전환", f"연속 빈 줄 개수가 규칙과 다름 ({rule}장면 전환은 '{marker}')", odd))
    if around_marker:
        issues.append(Issue("장면 전환", f"'{marker}' 앞뒤는 빈 줄 1개면 충분", around_marker))
    if breath and len(breaths) > max_breaths:
        issues.append(Issue("장면 전환", f"호흡 빈 줄 {len(breaths)}번 (한 화 {max_breaths}번 이하 권장)", breaths))
    other = [i for i, l in enumerate(lines, 1) if SCENE_MARK_RX.match(l) and l.strip() != marker]
    if other:
        issues.append(Issue("장면 전환", f"다른 전환 기호 사용 (작품 표기: '{marker}')", other))
    return issues
