"""작품 폴더의 AGENTS.md(Codex용 작품 지침)를 원본 md 문서에서 자동 생성한다.

Codex CLI는 실행할 때 작업 폴더의 AGENTS.md를 자동으로 읽는다. 읽기 전용 샌드박스에서도 작품 폴더의
파일을 직접 열 수 있으므로(2026-10-20 Codex 0.163.0으로 확인), AGENTS.md에는 핵심 지침(역할·규칙·작가 결정·문체·
회차 현황)만 담고 길어지는 기억 문서는 '참고 문서' 목록으로 가리킨다(기본). `--inline`이면 예전처럼
기억 문서 내용까지 한도 안에서 담는다. AGENTS.md는 생성물이므로 직접 고치지 않는다.

사용법:
    python -m tools.sync_agents                      # 작품 자동 판별
    python -m tools.sync_agents --project my_novel
    python -m tools.sync_agents --check              # 원본보다 오래됐으면 종료 코드 1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.project import ProjectConfig, load_project, read_section, read_text, resolve_project, setup_output_logging

logger = logging.getLogger(__name__)

AGENTS_NAME = "AGENTS.md"
DEFAULT_MAX_BYTES = 60_000  # second_opinion이 Codex에 project_doc_max_bytes=65_536을 넘기므로 그보다 여유 있게

ROLE = """## 너의 역할 (Codex)
- 너는 이 작품의 **2차 검토자**다. 1차 검토와 기억 관리는 Claude Code가 한다. 작가가 최종 결정한다.
- 파일을 만들거나 고치지 않는다. 원고를 고쳐 쓰지 말고 문제 위치·이유·짧은 대안만 낸다.
- 아래 내용은 Claude와 공유하는 원본 문서에서 자동으로 뽑은 것이다. 여기 적힌 [원고 확정]/[설정 확정]은 사실로, [인물의 추측]·[미정]·⚠초안은 사실이 아닌 것으로 취급한다.
- 이 폴더의 파일은 읽을 수 있다(읽기만). 아래 '참고 문서'에서 **매 검토 필수** 표시된 문서는 판단 전에 반드시 직접 열어 읽고, 나머지는 필요할 때 연다. 회차별 자료(기억 묶음·직전 회차 끝)는 검토 요청 프롬프트에도 함께 들어온다.
- 답의 맨 끝에 `읽은 파일:` 한 줄로 실제로 연 파일을 적는다."""

MUST_READ_NOTE = "매 검토 필수"


@dataclass
class Section:
    title: str
    body: str
    source: str
    required: bool = True


def _episodes_table(cfg: ProjectConfig) -> str:
    rows = ["| 회차 | 제목 | 상태 |", "|---|---|---|"]
    rows += [f"| {e.label} | {e.title} | {e.status} |" for e in cfg.episodes]
    return "\n".join(rows)


def _overview(cfg: ProjectConfig, raw: dict[str, Any]) -> str:
    rule = cfg.length
    lines = [
        f"- 제목: 「{cfg.title}」",
        f"- 연재 플랫폼: {cfg.platform or '(미지정)'} / 분량: {rule.basis} 최소 {rule.platform_min}자, 목표 {rule.target_min}~{rule.target_max}자",
    ]
    if raw.get("pov"):
        lines.append(f"- 시점: {raw['pov']}")
    marks = ", ".join(f"{name} {o}…{c}" for name, (o, c) in cfg.notation.pairs.items())
    lines.append(f"- 대사 기호: {marks}" + (f" / 줄머리: {', '.join(cfg.notation.line_prefixes)}" if cfg.notation.line_prefixes else ""))
    return "\n".join(lines)


INDEX_SUMMARY_CHARS = 110  # 인물 색인 한 줄 길이
RECENT_TIMELINE_ROWS = 4
LOOP_PROGRESS_CHARS = 70


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _entities_index(cfg: ProjectConfig) -> str:
    """인물·사물 짧은 색인(한 줄씩). 자세한 기억은 회차별 프롬프트의 기억 묶음으로 보낸다. 말투는 검토에 중요해 그대로 둔다."""
    path = cfg.path(cfg.entities)
    if not path.exists():
        return ""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for e in data.get("entities", []):
        line = f"- **{e.get('name')}** ({e.get('type', '')}): {_clip(e.get('summary', ''), INDEX_SUMMARY_CHARS)}"
        if e.get("speech"):
            line += f" / 말투: {_clip(e['speech'], 80)}"
        out.append(line)
    return "\n".join(out)


def _table_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """마크다운 표의 (머리 칸, 데이터 행) — 구분선 행 제외."""
    if not path.exists():
        return [], []
    rows = [l.strip() for l in read_text(path).split("\n") if l.strip().startswith("|")]
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    cells = [c for c in cells if not all(set(x) <= {"-", " ", ":"} for x in c)]
    return (cells[0], cells[1:]) if cells else ([], [])


def _open_loops_compact(cfg: ProjectConfig) -> str:
    """회수되지 않은 복선만, ID·질문·최근 진전(축약)·상태."""
    head, rows = _table_rows(cfg.path("memory/open_loops.md"))
    if not rows:
        return ""
    idx = {name: i for i, name in enumerate(head)}

    def col(r: list[str], name: str) -> str:
        """열 이름은 앞부분만 맞아도 찾는다('복선' ↔ '복선 / 미해결 질문')."""
        i = idx.get(name)
        if i is None:
            key = name.split()[0]
            i = next((j for n, j in idx.items() if n.startswith(key)), None)
        return r[i] if i is not None and i < len(r) else ""

    out = ["| ID | 복선/질문 | 최근 진전 | 상태 |", "|---|---|---|---|"]
    for r in rows:
        if col(r, "상태") == "회수":
            continue
        out.append(
            f"| {col(r, 'ID')} | {col(r, '복선 / 미해결 질문')} | {_clip(col(r, '최근 진전'), LOOP_PROGRESS_CHARS)} | {col(r, '상태')} |"
        )
    return "\n".join(out)


def _timeline_recent(cfg: ProjectConfig) -> str:
    """시간선은 최근 몇 회차와 고정 앵커만."""
    path = cfg.path("memory/timeline.md")
    head, rows = _table_rows(path)
    out: list[str] = []
    if rows:
        keep = rows[:1] + rows[-RECENT_TIMELINE_ROWS:] if len(rows) > RECENT_TIMELINE_ROWS + 1 else rows
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in keep]
    anchors = read_section(path, "고정 앵커")
    if anchors:
        out += ["", "\n".join(anchors.split("\n")[1:]).strip()]
    return "\n".join(out).strip()


def _strip_heading(section: str) -> str:
    lines = section.split("\n")
    return "\n".join(lines[1:]).strip() if lines and lines[0].startswith("## ") else section


def _doc_body(cfg: ProjectConfig, rel: str) -> str:
    """문서 본문을 첫 '# ' 제목 줄만 빼고 그대로."""
    if not rel or not cfg.path(rel).exists():
        return ""
    lines = cfg.path(rel).read_text(encoding="utf-8").strip().split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _characters(cfg: ProjectConfig) -> str:
    """주요 인물 현황 문서(storyforge.json의 characters)를 제목 줄만 빼고 그대로."""
    if not cfg.characters or not cfg.path(cfg.characters).exists():
        return ""
    lines = cfg.path(cfg.characters).read_text(encoding="utf-8").strip().split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def reference_docs(cfg: ProjectConfig) -> list[tuple[str, str]]:
    """Codex가 직접 열어 볼 문서 (경로, 용도). 인물 현황과 agents_extra는 매 검토 필수."""
    refs: dict[str, str] = {}
    if cfg.characters:
        refs[cfg.characters] = f"주요 인물 현황·말투 — **{MUST_READ_NOTE}**"
    for x in cfg.agents_extra:
        if x.get("file"):
            refs[str(x["file"])] = f"{x.get('title', '')} — **{MUST_READ_NOTE}**"
    for rel in cfg.memory_files:
        refs.setdefault(rel, "설정·기억 원본")
    refs.setdefault(cfg.entities, "인물·사물 색인(별칭 포함)")
    refs.setdefault("memory/timeline.md", "시간선")
    return [(rel, use) for rel, use in refs.items() if cfg.path(rel).exists()]


def must_read(cfg: ProjectConfig) -> list[str]:
    return [rel for rel, use in reference_docs(cfg) if MUST_READ_NOTE in use]


def _references(cfg: ProjectConfig) -> str:
    rows = ["| 파일 | 용도 |", "|---|---|"] + [f"| `{rel}` | {use} |" for rel, use in reference_docs(cfg)]
    rows += ["", "- 회차 원고는 `storyforge.json`의 회차 목록(`file`)에 있다. 연속성을 볼 때 직전 회차 원고를 직접 열어도 된다."]
    return "\n".join(rows)


def collect_sections(cfg: ProjectConfig, inline: bool = False) -> list[Section]:
    raw: dict[str, Any] = json.loads((cfg.root / "storyforge.json").read_text(encoding="utf-8"))
    readme = cfg.path("README.md")
    handoff = cfg.path("HANDOFF.md")
    style = cfg.path("style_profile.md")
    secs = [
        Section("작품 개요", _overview(cfg, raw), "storyforge.json"),
        Section("상태 태그와 운영 규칙", _strip_heading(read_section(readme, "운영 규칙")), "README.md › 운영 규칙"),
        Section("작품별 검토 규칙", _strip_heading(read_section(readme, "검토 규칙")), "README.md › 검토 규칙"),
        Section("작가가 확정한 결정", _strip_heading(read_section(handoff, "2.")), "HANDOFF.md › 2"),
        Section("작가 결정 대기 (사실로 쓰지 말 것)", _strip_heading(read_section(handoff, "3.")), "HANDOFF.md › 3"),
        Section("문체 기준: 요약", _strip_heading(read_section(style, "0.")), "style_profile.md › 0"),
        Section("문체 기준: 피할 것", _strip_heading(read_section(style, "2.")), "style_profile.md › 2"),
        Section("회차 현황", _episodes_table(cfg), "storyforge.json"),
    ]
    if not inline:
        secs.append(Section("참고 문서 (직접 열어 읽을 것)", _references(cfg), "storyforge.json"))
        return [s for s in secs if s.body]
    secs += [
        # 인물 현황은 선택 섹션 가운데 가장 늦게 뺀다(아래 순서의 뒤에서부터 뺌)
        Section("주요 인물 현황", _characters(cfg), cfg.characters or "characters", required=False),
        *[
            Section(str(x.get("title", x.get("file", ""))), _doc_body(cfg, str(x.get("file", ""))), str(x.get("file", "")), required=False)
            for x in cfg.agents_extra
        ],
        # 아래 기억 색인은 짧게만. 회차별 자세한 기억은 검토 요청 프롬프트의 '기억 묶음'으로 온다.
        Section("인물·사물 색인", _entities_index(cfg), cfg.entities, required=False),
        Section("진행 중인 복선 (회수된 것 제외)", _open_loops_compact(cfg), "memory/open_loops.md", required=False),
        Section("최근 시간선", _timeline_recent(cfg), "memory/timeline.md", required=False),
    ]
    return [s for s in secs if s.body]


def render(cfg: ProjectConfig, sections: list[Section], stamp: str) -> str:
    head = [
        f"# AGENTS.md — 「{cfg.title}」 작품 지침 (자동 생성)",
        "",
        f"> 생성: {stamp} · `python -m tools.sync_agents`가 원본 문서에서 만든 파일. **직접 고치지 말고 원본을 고친 뒤 다시 생성.**",
        "> 원본: " + ", ".join(dict.fromkeys(s.source.split(" ›")[0] for s in sections)),
        "",
        ROLE,
    ]
    # 섹션 안의 '## ' 제목은 한 단계 내려 AGENTS.md의 절 구조를 유지한다
    body = [f"## {s.title}\n> 출처: {s.source}\n\n" + ("\n" + s.body).replace("\n## ", "\n### ")[1:] for s in sections]
    return "\n".join(head) + "\n\n" + "\n\n".join(body) + "\n"


def build(
    cfg: ProjectConfig, max_bytes: int = DEFAULT_MAX_BYTES, stamp: str | None = None, inline: bool = False
) -> tuple[str, list[str]]:
    """AGENTS.md 내용과, 한도 때문에 뺀 섹션 목록."""
    stamp = stamp or datetime.now().strftime("%Y-%m-%d %H:%M")
    sections = collect_sections(cfg, inline)
    dropped: list[str] = []
    text = render(cfg, sections, stamp)
    # 한도를 넘으면 선택 섹션을 뒤에서부터 뺀다
    while len(text.encode("utf-8")) > max_bytes:
        optional = [s for s in sections if not s.required]
        if not optional:
            logger.warning("필수 섹션만으로도 %d바이트를 넘습니다.", max_bytes)
            break
        victim = optional[-1]
        sections.remove(victim)
        dropped.append(victim.title)
        text = render(cfg, sections, stamp)
    return text, dropped


def source_paths(cfg: ProjectConfig) -> list[Path]:
    rels = ["storyforge.json", "README.md", "HANDOFF.md", "style_profile.md", cfg.entities, "memory/timeline.md", "memory/open_loops.md"]
    if cfg.characters:
        rels.append(cfg.characters)
    rels += [str(x.get("file", "")) for x in cfg.agents_extra if x.get("file")]
    return [cfg.path(r) for r in rels if cfg.path(r).exists()]


def is_stale(cfg: ProjectConfig) -> bool:
    target = cfg.path(AGENTS_NAME)
    if not target.exists():
        return True
    mtime = target.stat().st_mtime
    return any(p.stat().st_mtime > mtime for p in source_paths(cfg))


def sync(cfg: ProjectConfig, max_bytes: int = DEFAULT_MAX_BYTES, inline: bool = False) -> tuple[Path, int, list[str]]:
    text, dropped = build(cfg, max_bytes, inline=inline)
    target = cfg.path(AGENTS_NAME)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target, len(text.encode("utf-8")), dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AGENTS.md(Codex용 작품 지침) 생성")
    parser.add_argument("--project", type=Path, help="작품 폴더 또는 novels/ 아래 이름")
    parser.add_argument("--check", action="store_true", help="원본보다 오래됐는지만 확인(오래됐으면 1)")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--inline", action="store_true", help="기억 문서를 목록 대신 내용째 담음(예전 방식)")
    args = parser.parse_args(argv)
    out = setup_output_logging()
    try:
        cfg = load_project(resolve_project(args.project))
        if args.check:
            stale = is_stale(cfg)
            out.info("AGENTS.md: " + ("갱신 필요" if stale else "최신"))
            return 1 if stale else 0
        target, size, dropped = sync(cfg, args.max_bytes, args.inline)
        msg = f"{target} 생성 ({size:,}바이트 / 한도 {args.max_bytes:,})"
        if dropped:
            msg += f" — 한도 초과로 제외: {', '.join(dropped)}"
        out.info(msg)
    except (OSError, ValueError) as e:
        logger.error("AGENTS.md 생성 실패: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
