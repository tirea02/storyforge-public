"""기억 검색(라이트 RAG): 인물·사물 이름으로 설정 문서와 확정 원고에서 관련 기억을 모아 맥락 묶음을 만든다.

사용법:
    # 이름으로 검색 (--project: novels/ 아래 작품 이름 또는 작품 폴더 경로)
    python -m tools.recall --project my_novel 등불새 아버지
    # 원고/기획 파일에 등장하는 대상을 자동으로 찾아 검색 (작품은 파일 위치로 자동 판별)
    python -m tools.recall --from-file novels/my_novel/04화_샘플.txt
    # 직전 회차 마지막 장면까지 포함(다음 화 집필용)
    python -m tools.recall --from-file novels/<작품>/기획.md --recent 30 -o 맥락.md
    # 등록된 작품/대상 목록
    python -m tools.recall --novels
    python -m tools.recall --project my_novel --list

원칙:
    - 설정 문서의 상태 태그([원고 확정], [인물의 추측] 등)를 그대로 보존해 보여 준다.
    - 원문 인용은 기본적으로 '원고 확정' 회차에서만 가져온다(--include-drafts로 초안 포함).
    - 최근 회차를 우선한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.project import Episode, ProjectConfig, list_novels, load_project, read_text, resolve_project, setup_output_logging

logger = logging.getLogger(__name__)

MIN_ALIAS_LEN = 2


@dataclass
class Entity:
    id: str
    name: str
    type: str
    aliases: list[str]
    summary: str = ""
    speech: str = ""
    first_episode: int | None = None

    def terms(self) -> list[str]:
        seen: list[str] = []
        for t in [self.name, *self.aliases]:
            if len(t) >= MIN_ALIAS_LEN and t not in seen:
                seen.append(t)
        return seen


@dataclass
class MemoryLine:
    source: str
    heading: str
    text: str


@dataclass
class Quote:
    episode: Episode
    line_no: int
    text: str


@dataclass
class EntityPack:
    entity: Entity
    memory: list[MemoryLine] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)


def load_entities(cfg: ProjectConfig) -> list[Entity]:
    path = cfg.path(cfg.entities)
    if not path.exists():
        logger.warning("엔티티 색인이 없습니다: %s", path)
        return []
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    keys = {"id", "name", "type", "aliases", "summary", "speech", "first_episode"}
    return [Entity(**{k: v for k, v in e.items() if k in keys}) for e in raw.get("entities", [])]


def resolve_queries(queries: list[str], entities: list[Entity]) -> tuple[list[Entity], list[str]]:
    """검색어를 엔티티로 매핑. 매핑되지 않은 검색어는 자유 키워드로 남긴다."""
    found: list[Entity] = []
    free: list[str] = []
    for q in queries:
        match = [
            e for e in entities
            if q == e.id or q == e.name or q in e.aliases or q in e.name or any(a in q for a in e.terms())
        ]
        if match:
            for e in match:
                if e not in found:
                    found.append(e)
        else:
            free.append(q)
    return found, free


def detect_entities(text: str, entities: list[Entity], min_hits: int = 1) -> list[tuple[Entity, int]]:
    """텍스트에 등장하는 엔티티와 등장 횟수(많은 순)."""
    scored: list[tuple[Entity, int]] = []
    for e in entities:
        n = sum(text.count(t) for t in e.terms())
        if n >= min_hits:
            scored.append((e, n))
    return sorted(scored, key=lambda x: -x[1])


def scan_memory_files(cfg: ProjectConfig, terms: list[str]) -> list[MemoryLine]:
    """설정 문서에서 검색어가 들어간 항목(글머리표·표 행)을 제목과 함께 모은다."""
    results: list[MemoryLine] = []
    for rel in cfg.memory_files:
        path = cfg.path(rel)
        if not path.exists():
            continue
        heading = ""
        for line in read_text(path).split("\n"):
            s = line.strip()
            if s.startswith("#"):
                heading = s.lstrip("#").strip()
                continue
            if not (s.startswith(("-", "*", "|")) or re.match(r"^\d+\.", s)):
                continue
            if s.startswith("|") and set(s.replace("|", "").strip()) <= {"-", " "}:
                continue
            if any(t in s for t in terms):
                results.append(MemoryLine(source=rel, heading=heading, text=s))
    return results


def scan_manuscripts(cfg: ProjectConfig, terms: list[str], include_drafts: bool, limit: int) -> list[Quote]:
    """원고에서 검색어가 등장한 줄. 최근 회차부터 limit개."""
    eps = cfg.episodes if include_drafts else cfg.confirmed_episodes()
    quotes: list[Quote] = []
    for ep in sorted(eps, key=lambda e: -e.no):
        path = cfg.path(ep.file)
        if not path.exists():
            logger.warning("원고 파일 없음: %s", path)
            continue
        lines = read_text(path).split("\n")
        hits = [(i, l.strip()) for i, l in enumerate(lines, 1) if l.strip() and any(t in l for t in terms)]
        for i, l in reversed(hits):
            quotes.append(Quote(ep, i, l))
            if len(quotes) >= limit:
                return quotes
    return quotes


def recent_tail(cfg: ProjectConfig, n_lines: int, include_drafts: bool) -> tuple[Episode, list[str]] | None:
    eps = cfg.episodes if include_drafts else cfg.confirmed_episodes()
    if not eps:
        return None
    last = max(eps, key=lambda e: e.no)
    lines = [l.strip() for l in read_text(cfg.path(last.file)).split("\n") if l.strip()]
    return last, lines[-n_lines:]


def build_packs(
    cfg: ProjectConfig, targets: list[Entity], free_terms: list[str], quotes_per: int, include_drafts: bool
) -> list[EntityPack]:
    packs: list[EntityPack] = []
    for e in targets:
        terms = e.terms()
        packs.append(
            EntityPack(
                entity=e,
                memory=scan_memory_files(cfg, terms),
                quotes=scan_manuscripts(cfg, terms, include_drafts, quotes_per),
            )
        )
    for t in free_terms:
        pseudo = Entity(id=f"kw:{t}", name=t, type="키워드", aliases=[t])
        packs.append(
            EntityPack(
                entity=pseudo,
                memory=scan_memory_files(cfg, [t]),
                quotes=scan_manuscripts(cfg, [t], include_drafts, quotes_per),
            )
        )
    return packs


def _clip(s: str, n: int = 160) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def render_pack(pack: EntityPack, budget: int) -> str:
    e = pack.entity
    out: list[str] = [f"## {e.name} ({e.type})"]
    if e.summary:
        out.append(f"- 요약: {e.summary}")
    if e.speech:
        out.append(f"- 말투: {e.speech}")

    def used() -> int:
        return sum(len(x) + 1 for x in out)

    # 복선 표 → 설정집 → 회차 기록 → 기타 순으로 우선
    def prio(m: MemoryLine) -> int:
        order = ["open_loops", "설정집", "회차별", "timeline", "기획", "검증"]
        for i, k in enumerate(order):
            if k in m.source:
                return i
        return len(order)

    seen: set[str] = set()
    mem_lines: list[str] = []
    for m in sorted(pack.memory, key=prio):
        if m.text in seen:
            continue
        seen.add(m.text)
        mem_lines.append(f"  - ({Path(m.source).stem} › {m.heading}) {_clip(m.text, 220)}")
    if mem_lines:
        out.append("- 기록:")
        for ml in mem_lines:
            if used() + len(ml) > budget * 0.75:
                out.append("  - …(기록 더 있음, 원문 문서 참고)")
                break
            out.append(ml)
    if pack.quotes:
        out.append("- 원고 인용(최근순):")
        for q in pack.quotes:
            ql = f"  - {q.episode.label} {q.line_no}행: {_clip(q.text)}"
            if used() + len(ql) > budget:
                break
            out.append(ql)
    return "\n".join(out)


def render(cfg: ProjectConfig, packs: list[EntityPack], max_chars: int, tail: tuple[Episode, list[str]] | None) -> str:
    header = [
        f"# 기억 묶음 — {cfg.title}",
        "> 상태 태그 그대로 읽을 것: [원고 확정] 사실 / [설정 확정] 작가 결정 / [기획]·[후보] 방향 / [인물의 추측] 사실 아님 / ⚠ 초안.\n"
        "> 대상: " + (", ".join(p.entity.name for p in packs) or "(없음)"),
    ]
    body_budget = max_chars - sum(len(h) for h in header)
    tail_block = ""
    if tail:
        ep, lines = tail
        tail_block = "\n".join([f"## 직전 회차 마지막 장면 — {ep.label} 「{ep.title}」", *[f"> {l}" for l in lines]])
        body_budget -= len(tail_block)
    per = max(400, body_budget // max(1, len(packs)))
    blocks = [render_pack(p, per) for p in packs]
    parts = header + blocks
    if tail_block:
        parts.append(tail_block)
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(parts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="기억 검색(라이트 RAG)")
    parser.add_argument("queries", nargs="*", help="인물·사물 이름 또는 키워드")
    parser.add_argument("--project", type=Path, help="작품 폴더 또는 novels/ 아래 작품 이름(생략 시 자동 판별)")
    parser.add_argument("--novels", action="store_true", help="등록된 작품 목록")
    parser.add_argument("--from-file", type=Path, help="이 파일에 등장하는 대상을 자동 검색")
    parser.add_argument("--min-hits", type=int, default=2, help="--from-file 자동 검색 시 최소 등장 횟수")
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--quotes", type=int, default=4, help="대상별 원고 인용 최대 개수")
    parser.add_argument("--recent", type=int, default=0, help="직전 확정 회차 마지막 N줄 포함")
    parser.add_argument("--include-drafts", action="store_true", help="초안 회차도 인용 대상에 포함")
    parser.add_argument("--list", action="store_true", help="등록된 대상 목록만 출력")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args(argv)
    out = setup_output_logging()
    try:
        if args.novels:
            for p in list_novels():
                out.info(f"- {p.name}: {load_project(p).title}")
            return 0
        cfg = load_project(resolve_project(args.project, args.from_file))
        entities = load_entities(cfg)
        if args.list:
            for e in entities:
                out.info(f"- {e.name} [{e.id}] ({e.type}) 검색어: {', '.join(e.terms())}")
            return 0
        targets, free = resolve_queries(args.queries, entities)
        if args.from_file:
            for e, n in detect_entities(read_text(args.from_file), entities, args.min_hits):
                if e not in targets:
                    targets.append(e)
                logger.info("자동 감지: %s %d회", e.name, n)
        if not targets and not free:
            logger.error("검색 대상이 없습니다. 이름을 주거나 --from-file 을 쓰세요. (--list 로 목록 확인)")
            return 1
        tail = recent_tail(cfg, args.recent, args.include_drafts) if args.recent else None
        packs = build_packs(cfg, targets, free, args.quotes, args.include_drafts)
        text = render(cfg, packs, args.max_chars, tail)
        if args.output:
            args.output.write_text(text, encoding="utf-8", newline="\n")
            out.info(f"{args.output} 저장 ({len(text)}자, 대상 {len(packs)}개)")
        else:
            out.info(text)
    except (OSError, ValueError, KeyError) as e:
        logger.error("기억 검색 실패: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
