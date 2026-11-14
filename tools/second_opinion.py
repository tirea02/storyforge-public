"""교차 검토(세컨드 오피니언): Codex CLI에 같은 원고를 검토시켜 Claude의 검토와 비교한다.

외부 API 키를 쓰지 않는다. 작가의 ChatGPT 구독으로 로그인한 Codex CLI(`codex exec`)를 호출한다.

사용법:
    # 프롬프트만 만들기(Codex 없이도 동작)
    python -m tools.second_opinion novels/<작품>/<원고>.txt --dry-run
    # Codex 호출 → novels/<작품>/reviews/<원고>_codex.md
    python -m tools.second_opinion novels/<작품>/<원고>.txt
    # Claude가 반박한 항목만 재검토(2라운드)
    python -m tools.second_opinion novels/<작품>/<원고>.txt --rebuttal novels/<작품>/reviews/<원고>_claude.md

사전 준비(작가가 1회): npm i -g @openai/codex  →  codex login (ChatGPT 계정)
Codex CLI 옵션은 버전마다 바뀔 수 있다. 실패하면 `codex exec --help`로 확인하고 --codex-args로 덮어쓴다.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from tools import sync_agents
from tools.check_episode import check_file, render as render_check
from tools.project import ProjectConfig, find_project_root, load_project, read_section, read_text, setup_output_logging
from tools.recall import build_packs, detect_entities, load_entities, render as render_recall

logger = logging.getLogger(__name__)

# Codex는 AGENTS.md를 기본 32,768바이트까지만 읽고 나머지는 잘라 버린다(2026-10-17 실험으로 확인).
# 평소에는 sync_agents가 28KB 이하로 유지하지만, 넘더라도 잘리지 않도록 한도를 64KB로 올려 둔다.
CODEX_PROJECT_DOC_MAX_BYTES = 65_536
DEFAULT_CODEX_ARGS = [
    "exec",
    "-c",
    f"project_doc_max_bytes={CODEX_PROJECT_DOC_MAX_BYTES}",
    "--sandbox",
    "read-only",
    "--skip-git-repo-check",
]

REVIEW_INSTRUCTIONS = """너는 한국 웹소설 「{title}」의 **2차 검토자**다. 1차 검토는 다른 AI(Claude)가 한다.
너의 역할은 1차 검토자가 놓치기 쉬운 문제를 찾는 것이다. 칭찬은 하지 말고 문제만 찾는다.
원고를 고쳐 쓰지 말고, 문제 위치와 이유, 짧은 대안만 제시한다. 파일을 수정하지 않는다.

검토 기준(우선순위 순):
1. 설정 충돌: 아래 '기억 묶음'의 [원고 확정]/[설정 확정]과 어긋나는 서술. [인물의 추측]이나 ⚠초안을 사실처럼 쓴 곳.
2. 연속성: 직전 회차와 시간·장소·상황이 이어지지 않는 곳, 이전 회차와 같은 문답·개그 반복.
3. AI 문체 습관: '문체 기준'의 '피할 것' 목록 + 그 밖에 기계적으로 읽히는 리듬(박자 맞추기용 대답, 설명 덧붙이기, 요약·다짐, 상투어).
4. 인물 말투 일관성, 그리고 '작품별 검토 규칙'에 적힌 제약.
5. 웹소설 독자 관점: 늘어지는 구간, 보상 없는 장면.

출력 형식(마크다운 표 하나 + 총평 2줄):
| # | 행 | 분류 | 문제 | 근거 | 제안 | 확신(상/중/하) |
"""

REBUTTAL_INSTRUCTIONS = """아래는 네(2차 검토자)가 낸 지적에 대한 1차 검토자(Claude)의 답변이다.
'반박' 또는 '보류'로 표시된 항목만 다시 판단하라. 각 항목에 대해 '철회' / '유지(추가 근거)' 중 하나로 답하고, 새 지적은 추가하지 마라.

출력 형식:
| # | 판정(철회/유지) | 이유 |
"""


def style_digest(cfg: ProjectConfig) -> str:
    """문체 프로필의 요약(0번)과 피할 것(2번)만 잘라 낸다."""
    path = cfg.path("style_profile.md")
    parts = [read_section(path, "0."), read_section(path, "2.")]
    return "\n\n".join(p for p in parts if p) or "(문체 프로필 없음)"


def review_rules(cfg: ProjectConfig) -> str:
    """작품 README의 '## 검토 규칙' 절(작품 고유 제약)."""
    return read_section(cfg.path("README.md"), "검토 규칙") or "(없음)"


def previous_episode_tail(episode: Path, cfg: ProjectConfig, n_lines: int = 30) -> str:
    """직전 회차(초안 포함) 마지막 n줄. 연속성의 핵심이라 Codex가 파일을 열지 않아도 보이게 프롬프트에도 넣는다."""
    current = next((e for e in cfg.episodes if e.file == episode.name), None)
    if current is None:
        return ""
    prev = [e for e in cfg.episodes if e.no < current.no]
    if not prev:
        return ""
    last = max(prev, key=lambda e: e.no)
    path = cfg.path(last.file)
    if not path.exists():
        return ""
    lines = [l.strip() for l in read_text(path).split("\n") if l.strip()]
    status = "" if last.status == "원고 확정" else f" (⚠{last.status})"
    return f"# 직전 회차 마지막 장면 — {last.label}{status}\n" + "\n".join(f"> {l}" for l in lines[-n_lines:])


def timeline_text(cfg: ProjectConfig) -> str:
    path = cfg.path("memory/timeline.md")
    return "# 시간선\n" + read_text(path) if path.exists() else ""


def must_read_block(episode: Path, cfg: ProjectConfig) -> str:
    """Codex가 판단 전에 직접 열어 읽을 파일(인물 현황·설정 대장 + 직전 회차 원고)과 확인 요청."""
    files = sync_agents.must_read(cfg)
    current = next((e for e in cfg.episodes if e.file == episode.name), None)
    prev = [e for e in cfg.episodes if current and e.no < current.no and cfg.path(e.file).exists()]
    if prev:
        files.append(max(prev, key=lambda e: e.no).file)
    lines = ["# 먼저 직접 열어 읽을 파일 (판단 전에 필수)"] + [f"- `{f}`" for f in files]
    lines.append("- 그 밖의 기억 문서는 AGENTS.md '참고 문서' 목록에서 필요할 때 연다.")
    lines.append("- 답의 맨 끝에 `읽은 파일: …` 한 줄로 실제로 연 파일을 모두 적는다.")
    return "\n".join(lines)


def build_prompt(episode: Path, cfg: ProjectConfig, max_memory_chars: int = 6000, lean: bool = False) -> str:
    """검토 요청 프롬프트.

    lean=True: 작품 공통 지침(문체 기준·검토 규칙·시간선)은 Codex가 자동으로 읽는 AGENTS.md에 있으므로 빼고,
    이 회차에 필요한 자료(기억 묶음·직전 회차 끝·기계 점검·원고)만 보낸다.
    """
    manuscript = read_text(episode)
    entities = load_entities(cfg)
    targets = [e for e, _ in detect_entities(manuscript, entities, min_hits=2)]
    packs = build_packs(cfg, targets, [], quotes_per=3, include_drafts=False)
    memory = render_recall(cfg, packs, max_memory_chars, tail=None)
    check = render_check(check_file(episode, cfg))
    numbered = "\n".join(f"{i:>4}: {line}" for i, line in enumerate(manuscript.split("\n"), 1))
    shared = (
        ["(작품 지침·문체 기준·검토 규칙은 AGENTS.md 참고)", must_read_block(episode, cfg)]
        if lean
        else [
            "# 문체 기준\n" + style_digest(cfg),
            "# 작품별 검토 규칙\n" + review_rules(cfg),
            timeline_text(cfg),
        ]
    )
    return "\n\n".join(
        [
            REVIEW_INSTRUCTIONS.format(title=cfg.title),
            *shared,
            memory,
            previous_episode_tail(episode, cfg),
            "# 기계 점검 결과(참고)\n" + check,
            f"# 원고: {episode.name} (행 번호 포함)\n" + numbered,
        ]
    )


def build_rebuttal_prompt(codex_review: Path, claude_reply: Path) -> str:
    return "\n\n".join(
        [
            REBUTTAL_INSTRUCTIONS,
            "# 너의 1차 지적\n" + read_text(codex_review),
            "# Claude의 답변\n" + read_text(claude_reply),
        ]
    )


def run_codex(prompt: str, workdir: Path, out_file: Path, codex_args: list[str], timeout: int) -> int:
    exe = shutil.which("codex")
    if exe is None:
        logger.error("codex CLI를 찾을 수 없습니다. `npm i -g @openai/codex` 후 `codex login`을 먼저 하세요.")
        return 2
    cmd = [exe, *codex_args, "-C", str(workdir), "--output-last-message", str(out_file), "-"]
    logger.info("실행: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, input=prompt, text=True, encoding="utf-8", capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        logger.error("codex 응답 시간 초과(%d초)", timeout)
        return 3
    if proc.returncode != 0:
        logger.error("codex 실패(코드 %d): %s", proc.returncode, (proc.stderr or proc.stdout)[-800:])
        return proc.returncode
    if not out_file.exists() and proc.stdout:
        out_file.write_text(proc.stdout, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex 교차 검토")
    parser.add_argument("episode", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="프롬프트 파일만 만들고 Codex는 호출하지 않음")
    parser.add_argument("--rebuttal", type=Path, help="Claude 답변 파일(2라운드)")
    parser.add_argument("--reviews-dir", type=Path, help="결과 폴더(기본: <프로젝트>/reviews)")
    parser.add_argument("--codex-args", nargs="*", help="codex 인자 덮어쓰기(기본: exec --sandbox read-only --skip-git-repo-check)")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--full-prompt", action="store_true", help="AGENTS.md를 쓰지 않고 작품 지침을 프롬프트에 모두 넣음"
    )
    args = parser.parse_args(argv)
    out = setup_output_logging()
    try:
        root = find_project_root(args.episode)
        if root is None:
            logger.error("storyforge.json이 있는 프로젝트 폴더를 찾지 못했습니다.")
            return 1
        cfg = load_project(root)
        rdir = args.reviews_dir or root / "reviews"
        rdir.mkdir(parents=True, exist_ok=True)
        stem = args.episode.stem
        lean = not args.full_prompt
        if lean:
            target, size, dropped = sync_agents.sync(cfg)
            out.info(f"AGENTS.md 갱신: {target.name} ({size:,}바이트)" + (f", 제외: {', '.join(dropped)}" if dropped else ""))
        if args.rebuttal:
            prompt = build_rebuttal_prompt(rdir / f"{stem}_codex.md", args.rebuttal)
            prompt_file, result_file = rdir / f"{stem}_rebuttal_prompt.md", rdir / f"{stem}_codex_r2.md"
        else:
            prompt = build_prompt(args.episode, cfg, lean=lean)
            prompt_file, result_file = rdir / f"{stem}_prompt.md", rdir / f"{stem}_codex.md"
        prompt_file.write_text(prompt, encoding="utf-8", newline="\n")
        out.info(f"프롬프트 저장: {prompt_file} ({len(prompt)}자)")
        if args.dry_run:
            return 0
        code = run_codex(prompt, root, result_file, args.codex_args or DEFAULT_CODEX_ARGS, args.timeout)
        if code == 0:
            out.info(f"Codex 검토 저장: {result_file}")
        return code
    except (OSError, ValueError) as e:
        logger.error("교차 검토 실패: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
