"""Codex 작업공간: 많이 읽는 1차 작업(대조·사실 확인·기억 점검 판정·교차 검토)을 Codex CLI에 맡긴다.

역할 나누기(defaults/작가_작업규칙.md §7): Codex는 근거를 찾아 표로 내고, Claude가 확인해 카드로 올린다.
Codex는 작품 폴더의 `codex/` 안에만 쓸 수 있다(`--sandbox workspace-write`, 작업 폴더 = codex/).
원고·기억 문서는 읽기만 한다. 호출마다 새로 시작하고, 이어받을 것은 `codex/작업노트.md`로 넘긴다.

작업공간(처음 실행할 때 자동 생성):
    novels/<작품>/codex/AGENTS.md    ← 생성물(defaults/codex/AGENTS.md 틀 + 작품 설정)
    novels/<작품>/codex/작업노트.md   ← 인계 메모(Claude가 알려 주는 것 / Codex 기록)
    novels/<작품>/codex/결과/         ← NN화_대조.md, NN화_사실확인.md …

사용법:
    python -m tools.codex_worker --project <작품> 대조 40          # 40화 초안 ↔ 직전 확정 회차
    python -m tools.codex_worker --project <작품> 사실확인 40
    python -m tools.codex_worker --project <작품> 기억점검 reviews/기억점검/<보고서>.md
    python -m tools.codex_worker --project <작품> 교차검토 39
    python -m tools.codex_worker --project <작품> 근거대조 codex/결과/40화_대조.md   # 근거만 다시 대조
    (--dry-run: 지시문만 만들고 Codex는 부르지 않음)

결과 파일 끝에 '근거 자동 대조'가 붙는다: Codex가 낸 `근거: N화 L줄 「원문」`이 실제 원문과 맞는지.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tools import sync_agents
from tools.memory_audit import fragments, norm
from tools.project import DEFAULTS_DIR, Episode, ProjectConfig, load_project, read_text, resolve_project, setup_output_logging

TEMPLATE_DIR = DEFAULTS_DIR / "codex"
KINDS = ("대조", "사실확인", "기억점검", "교차검토")
CITE_RE = re.compile(r"근거[:：]\s*(\d{1,3})화\s*L(\d+)\s*줄?\s*「([^」]+)」")
WINDOW = 3
CODEX_PROJECT_DOC_MAX_BYTES = 65_536


def workspace(cfg: ProjectConfig) -> Path:
    return cfg.root / "codex"


def notation_text(cfg: ProjectConfig) -> str:
    return ", ".join(f"{name} {o}…{c}" for name, (o, c) in cfg.notation.pairs.items())


def ensure_workspace(cfg: ProjectConfig) -> Path:
    """codex/ 폴더·결과 폴더·작업노트(없을 때만)를 만들고 codex/AGENTS.md를 다시 만든다."""
    ws = workspace(cfg)
    (ws / "결과").mkdir(parents=True, exist_ok=True)
    note = ws / "작업노트.md"
    if not note.exists():
        note.write_text(read_text(TEMPLATE_DIR / "작업노트.md").replace("{title}", cfg.title), encoding="utf-8", newline="\n")
    agents = read_text(TEMPLATE_DIR / "AGENTS.md").replace("{title}", cfg.title).replace("{notation}", notation_text(cfg))
    (ws / "AGENTS.md").write_text(agents, encoding="utf-8", newline="\n")
    return ws


def find_episode(cfg: ProjectConfig, no: int) -> Episode:
    ep = next((e for e in cfg.episodes if e.no == no), None)
    if ep is None:
        raise ValueError(f"{no}화가 storyforge.json에 없습니다.")
    return ep


def previous_confirmed(cfg: ProjectConfig, no: int) -> Episode | None:
    prev = [e for e in cfg.confirmed_episodes() if e.no < no]
    return max(prev, key=lambda e: e.no) if prev else None


def build_prompt(cfg: ProjectConfig, kind: str, target: str, file: str = "") -> tuple[str, str]:
    """(지시문, 결과 파일 이름). file: 같은 회차의 다른 판(예: 40화_v2.txt)을 대상으로."""
    tpl = read_text(TEMPLATE_DIR / "작업" / f"{kind}.md")
    if kind == "기억점검":
        rel = Path(target).as_posix()
        body = tpl.replace("{target}", f"../{rel}")
        return body, f"기억점검_{Path(target).stem}.md"
    ep = find_episode(cfg, int(target))
    if file:
        ep = Episode(ep.no, ep.title, file, "초안")
    prev = previous_confirmed(cfg, ep.no)
    against = f"../{prev.file}" if prev else "(없음)"
    body = (
        tpl.replace("{target}", f"../{ep.file}")
        .replace("{against}", against)
        .replace("{target_label}", ep.label)
        .replace("{against_label}", prev.label if prev else "")
    )
    if kind == "교차검토":
        from tools.second_opinion import build_prompt as review_material

        material = review_material(cfg.path(ep.file), cfg, lean=True)
        keep = [s for s in material.split("\n\n# ") if s.startswith(("기억 묶음", "기계 점검", "직전 회차"))]
        body += "\n\n" + "\n\n".join("# " + s for s in keep)
    status = "" if ep.status == "원고 확정" else f" — 이 회차는 '{ep.status}'"
    head = f"작품: 「{cfg.title}」. 작업공간 규칙은 이 폴더의 AGENTS.md, 먼저 `작업노트.md`를 읽는다.{status}"
    suffix = "_" + Path(file).stem.split("_", 1)[-1] if file else ""
    return head + "\n\n" + body, f"{ep.no:02d}화{suffix}_{kind}.md"


@dataclass
class Citation:
    ep: int
    line: int
    quote: str
    verdict: str  # 맞음 / 줄 다름 / 원문에 없음 / 초안 회차 / 회차 없음
    actual: int | None = None


def verify_citations(text: str, cfg: ProjectConfig) -> list[Citation]:
    eps = {e.no: e for e in cfg.episodes}
    cache: dict[int, list[str]] = {}
    out: list[Citation] = []
    for m in CITE_RE.finditer(text):
        no, line, quote = int(m.group(1)), int(m.group(2)), m.group(3)
        ep = eps.get(no)
        if ep is None or not cfg.path(ep.file).exists():
            out.append(Citation(no, line, quote, "회차 없음"))
            continue
        if no not in cache:
            cache[no] = read_text(cfg.path(ep.file)).split("\n")
        lines = cache[no]
        frs = fragments(quote) or [norm(quote)]
        lo, hi = max(0, line - 1 - WINDOW), min(len(lines), line + WINDOW)
        near = norm("".join(lines[lo:hi]))
        if all(f in near for f in frs):
            verdict, actual = ("맞음" if ep.status == "원고 확정" else "초안 회차"), None
        else:
            hit = next((i + 1 for i, l in enumerate(lines) if frs[0] in norm(l)), None)
            if hit is not None and all(f in norm("".join(lines)) for f in frs):
                verdict, actual = "줄 다름", hit
            else:
                verdict, actual = "원문에 없음", None
        out.append(Citation(no, line, quote, verdict, actual))
    return out


def citation_report(cites: list[Citation]) -> str:
    counts = {v: sum(1 for c in cites if c.verdict == v) for v in ("맞음", "줄 다름", "원문에 없음", "초안 회차", "회차 없음")}
    lines = ["", "---", "## 근거 자동 대조 (tools.codex_worker)", "",
             " / ".join(f"{k} {v}" for k, v in counts.items() if v or k == "맞음") + f" (총 {len(cites)})"]
    for c in cites:
        if c.verdict == "맞음":
            continue
        extra = f" → 실제 L{c.actual}" if c.actual else ""
        lines.append(f"- ✘ {c.verdict}: {c.ep}화 L{c.line}{extra} 「{c.quote[:60]}」")
    return "\n".join(lines) + "\n"


def run_codex(prompt: str, ws: Path, out_file: Path, timeout: int) -> int:
    exe = shutil.which("codex")
    if exe is None:
        raise FileNotFoundError("codex CLI를 찾을 수 없습니다. `npm i -g @openai/codex` 후 `codex login`.")
    cmd = [exe, "exec", "-c", f"project_doc_max_bytes={CODEX_PROJECT_DOC_MAX_BYTES}", "--sandbox", "workspace-write",
           "--skip-git-repo-check", "-C", str(ws), "--output-last-message", str(out_file), "-"]
    proc = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"codex 실패(코드 {proc.returncode}): {(proc.stderr or proc.stdout)[-800:]}")
    if not out_file.exists() and proc.stdout:
        out_file.write_text(proc.stdout, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    out = setup_output_logging()
    ap = argparse.ArgumentParser(description="Codex 작업공간(대조·사실 확인·기억 점검·교차 검토)")
    ap.add_argument("kind", choices=[*KINDS, "근거대조"])
    ap.add_argument("target", help="회차 번호(대조·사실확인·교차검토), 보고서 경로(기억점검), 결과 경로(근거대조)")
    ap.add_argument("--project", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="지시문만 만들고 Codex는 부르지 않음")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--file", default="", help="같은 회차의 다른 판 파일(작품 폴더 기준, 예: 40화_v2.txt)")
    args = ap.parse_args(argv)
    try:
        cfg = load_project(resolve_project(args.project))
        if args.kind == "근거대조":
            path = cfg.path(args.target)
            text = read_text(path).split("\n---\n## 근거 자동 대조")[0]
            rep = citation_report(verify_citations(text, cfg))
            path.write_text(text.rstrip("\n") + "\n" + rep, encoding="utf-8")
            out.info(rep.strip())
            return 0
        ws = ensure_workspace(cfg)
        sync_agents.sync(cfg)
        prompt, name = build_prompt(cfg, args.kind, args.target, args.file)
        result = ws / "결과" / name
        (ws / "결과" / name.replace(".md", "_prompt.md")).write_text(prompt, encoding="utf-8", newline="\n")
        out.info(f"지시문: {result.with_name(name.replace('.md', '_prompt.md'))} ({len(prompt)}자)")
        if args.dry_run:
            return 0
        run_codex(prompt, ws, result, args.timeout)
        text = read_text(result)
        rep = citation_report(verify_citations(text, cfg))
        result.write_text(text.rstrip("\n") + "\n" + rep, encoding="utf-8")
        out.info(f"결과: {result}")
        out.info(rep.strip())
        return 0
    except subprocess.TimeoutExpired:
        out.error("codex 응답 시간 초과(%d초)", args.timeout)
        return 3
    except (OSError, ValueError, RuntimeError) as e:
        out.error("Codex 작업 실패: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
