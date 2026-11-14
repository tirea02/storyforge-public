"""기억 점검: 기억 문서에 따옴표로 인용한 대사·문구가 확정 원고에 실제로 있는지 대조한다.

Anthropic 'Dreaming'(기억을 원본 기록과 다시 대조해 고치는 단계)의 읽기 전용 축소판.
기억 문서는 고치지 않고 보고서만 만든다. 판단(진짜 오류인지)은 사람이 한다.

사용법:
    # 작품의 기억 문서 전부(memory_files + 인물 현황 + characters/*.md)
    python -m tools.memory_audit --project <작품>
    # 문서 하나만, 보고서 저장
    python -m tools.memory_audit --project <작품> memory/characters.md -o 점검.md

판정:
    맞음       — 인용이 줄에 적힌 회차(없으면 아무 회차) 원문에 있음. '…'로 줄인 인용은 조각마다 찾음
    다른 화     — 원문에는 있지만 줄에 적힌 회차가 아님(회차 표기 확인)
    근거 없음   — 확정 원고 어디에도 없음(바꿔 말함·잘못 기억·빠진 대사 → 사람이 확인)
    따옴표가 엉킨 것으로 보이는 조각(괄호·화살표·서식 포함, 너무 김)은 세지 않는다.

낡은 표시 점검(함께 나옴): 확정된 회차를 가리키는 ⚠, 이미 확정된 회차의 '예정·[기획]',
머리말 '기준: N화'가 최신 확정보다 오래됨, 복선 표(| L01 | …) 상태 칸이 넷 중 하나가 아님·'열림'인데 진전 있음.
회차별 기록·기획처럼 지난 계획이 역사로 남는 문서는 storyforge.json "audit_skip_plan"에 넣어 ⚠·'예정' 점검에서 뺀다.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from tools.project import ProjectConfig, load_project, read_text, resolve_project, setup_output_logging

QUOTE_RE = re.compile(r"『([^』\n]{2,})』|'([^'\n]{2,})'|\"([^\"\n]{2,})\"|‘([^’\n]{2,})’|“([^”\n]{2,})”")
EP_RE = re.compile(r"(\d{1,3})화")
NOISE_RE = re.compile(r"[()（）→*\[\]|]")
MAX_QUOTE = 80
MIN_FRAG = 4


@dataclass
class Finding:
    doc: str
    line_no: int
    quote: str
    claimed: list[int]
    found_in: list[int]

    @property
    def verdict(self) -> str:
        if not self.found_in:
            return "근거 없음"
        if not self.claimed or set(self.claimed) & set(self.found_in):
            return "맞음"
        return "다른 화"


def norm(s: str) -> str:
    """대조용 정규화: 공백·문장부호 차이를 무시."""
    return re.sub(r"[\s.,!?~\-—·…『』'\"‘’“”]", "", s)


def tangled(quote: str) -> bool:
    """따옴표 짝이 엉켜 잡힌 조각: 앞뒤가 빈칸이거나 쉼표·조사로 시작한다."""
    return quote != quote.strip() or quote[0] in ",.)」』" or quote.startswith(("으로 ", "로 ", "를 ", "을 ", "에 "))


def fragments(quote: str) -> list[str]:
    """'…'·'...'로 줄인 인용을 조각으로 나눈다. 너무 짧은 조각은 버린다."""
    parts = re.split(r"…+|\.{3,}", quote)
    return [n for n in (norm(p) for p in parts) if len(n) >= MIN_FRAG]


def load_manuscripts(cfg: ProjectConfig) -> dict[int, str]:
    out: dict[int, str] = {}
    for ep in cfg.confirmed_episodes():
        p = cfg.path(ep.file)
        if p.exists():
            out[ep.no] = norm(read_text(p))
    return out


def default_docs(cfg: ProjectConfig) -> list[str]:
    docs = list(cfg.memory_files)
    if cfg.characters and cfg.characters not in docs:
        docs.append(cfg.characters)
    char_dir = cfg.root / "characters"
    if char_dir.is_dir():
        docs += [f"characters/{p.name}" for p in sorted(char_dir.glob("*.md"))]
    return [d for d in dict.fromkeys(docs) if cfg.path(d).exists() and d.endswith(".md")]


def audit(doc_rel: str, text: str, manus: dict[int, str]) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        claimed = sorted({int(x) for x in EP_RE.findall(line) if int(x) in manus})
        for m in QUOTE_RE.finditer(line):
            q = next(g for g in m.groups() if g)
            if len(q) > MAX_QUOTE or NOISE_RE.search(q) or tangled(q):
                continue
            frags = fragments(q)
            if not frags:
                continue
            found = sorted(ep for ep, txt in manus.items() if all(f in txt for f in frags))
            findings.append(Finding(doc_rel, i, q, claimed, found))
    return findings


PLAN_RE = re.compile(r"(\d{1,3})화[^\n|]{0,30}?((?<!수정_)예정|\[기획\])")
BASIS_RE = re.compile(r"기준[:：]?\s*\**\s*(\d{1,3})화")
LOOP_RE = re.compile(r"^\| (L\d+) \|")
LOOP_STATUS = ("열림", "진행", "보류", "회수")


def stale_checks(doc_rel: str, text: str, latest: int, skip_plan: bool = False) -> list[str]:
    """낡은 표시 점검: 확정 회차에 남은 ⚠, 지난 회차의 '예정·[기획]', 오래된 '기준: N화', 복선 상태 칸.

    skip_plan: 지난 계획이 역사로 남는 문서(회차 기록·기획) — ⚠·예정 점검을 뺀다.
    """
    out: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        if "⚠" in line and not skip_plan:
            eps = [int(x) for x in EP_RE.findall(line)]
            if eps and max(eps) <= latest:
                out.append(f"{doc_rel} L{i} ⚠ 표시인데 언급한 회차({max(eps)}화)는 확정됨")
        if not skip_plan:
            for m in PLAN_RE.finditer(line):
                if int(m.group(1)) <= latest:
                    out.append(f"{doc_rel} L{i} '{m.group(0)[:40]}' — {m.group(1)}화는 이미 확정됨")
        lm = LOOP_RE.match(line)
        if lm:
            cells = line.split("|")
            if len(cells) > 5:
                status = cells[5].strip()
                if status not in LOOP_STATUS:
                    out.append(f"{doc_rel} L{i} {lm.group(1)} 상태 칸 '{status[:20]}' — 넷(열림·진행·보류·회수) 중 하나만")
                first = EP_RE.findall(cells[3])
                prog = [int(x) for x in EP_RE.findall(cells[4])]
                if status == "열림" and first and prog and max(prog) > int(first[0]):
                    out.append(f"{doc_rel} L{i} {lm.group(1)} '열림'인데 {max(prog)}화 진전이 있음 → 진행?")
    for i, line in enumerate(lines[:12], 1):
        m = BASIS_RE.search(line)
        if m and int(m.group(1)) < latest:
            out.append(f"{doc_rel} L{i} 머리말 '기준: {m.group(1)}화' — 최신 확정은 {latest}화")
    return out


def report(findings: list[Finding], docs: list[str], stale: list[str] | None = None) -> str:
    lines = ["# 기억 점검", "", "| 문서 | 인용 | 맞음 | 다른 화 | 근거 없음 |", "|---|---:|---:|---:|---:|"]
    for d in docs:
        fs = [f for f in findings if f.doc == d]
        c = {v: sum(1 for f in fs if f.verdict == v) for v in ("맞음", "다른 화", "근거 없음")}
        lines.append(f"| {d} | {len(fs)} | {c['맞음']} | {c['다른 화']} | {c['근거 없음']} |")
    total = len(findings)
    ok = sum(1 for f in findings if f.verdict == "맞음")
    lines += ["", f"합계 {total}개 중 맞음 {ok}개({ok * 100 // max(total, 1)}%)"]
    if stale is not None:
        lines.append(f"낡은 표시 {len(stale)}건")
    lines.append("")
    if stale:
        lines += ["## 낡은 표시", "", *[f"- {s}" for s in stale], ""]
    for verdict in ("근거 없음", "다른 화"):
        lines += [f"## {verdict}", ""]
        for f in findings:
            if f.verdict == verdict:
                lines.append(f"- {f.doc} L{f.line_no} '{f.quote}' — 적힌 화 {f.claimed or '-'} / 원문 {f.found_in or '-'}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    out = setup_output_logging()
    ap = argparse.ArgumentParser(description="기억 문서의 인용을 확정 원고와 대조(읽기 전용)")
    ap.add_argument("docs", nargs="*", help="점검할 문서(작품 폴더 기준). 없으면 기억 문서 전부")
    ap.add_argument("--project", type=Path, help="작품 이름 또는 폴더")
    ap.add_argument("-o", "--out", type=Path, help="보고서 저장 경로")
    args = ap.parse_args(argv)
    try:
        cfg = load_project(resolve_project(args.project))
        manus = load_manuscripts(cfg)
        docs = args.docs or default_docs(cfg)
        latest = max(manus) if manus else 0
        skip_plan = set(cfg.audit_skip_plan)
        findings: list[Finding] = []
        stale: list[str] = []
        for d in docs:
            text_d = read_text(cfg.path(d))
            findings += audit(d, text_d, manus)
            stale += stale_checks(d, text_d, latest, skip_plan=d in skip_plan)
        text = report(findings, docs, stale)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
            out.info("저장: %s", args.out)
            cut = text.index("## 낡은 표시") if stale else text.index("## 근거 없음")
            out.info(text[:cut].rstrip())
        else:
            out.info(text)
        return 0
    except Exception:
        out.exception("기억 점검 실패")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
