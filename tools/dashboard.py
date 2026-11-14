"""작품 대시보드(HTML) 생성: 진행 상황·결정 대기·체크리스트·복선·시간선을 한 페이지로.

원본은 작품 폴더의 md 문서와 storyforge.json이다. HTML은 생성물이므로 직접 고치지 않는다.
토큰을 쓰지 않고 로컬에서 다시 만들 수 있다.

사용법:
    python -m tools.dashboard                 # 작품 자동 판별 → <작품>/dashboard.html
    python -m tools.dashboard --open          # 만들고 브라우저 탭으로 열기
    python -m tools.dashboard --project my_novel -o 어딘가.html
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import markdown

from tools.check_episode import check_file
from tools.project import ProjectConfig, load_project, read_section, read_text, resolve_project, setup_output_logging

logger = logging.getLogger(__name__)

MD_EXTENSIONS = ["tables", "sane_lists", "fenced_code"]


@dataclass
class EpisodeRow:
    label: str
    title: str
    status: str
    file: str
    platform_chars: int | None
    verdict: str
    issues: int
    short_runs: int | None = None
    short_ratio: float = 0.0
    short_over: bool = False


def md_to_html(text: str) -> str:
    """마크다운 → HTML. '- [ ]'/'- [x]' 체크박스를 표시용 기호로 바꾼다."""
    text = re.sub(r"^(\s*)- \[ \] ", r"\1- ☐ ", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)- \[x\] ", r"\1- ☑ ", text, flags=re.MULTILINE | re.IGNORECASE)
    return markdown.markdown(text, extensions=MD_EXTENSIONS)


def strip_title(text: str) -> str:
    lines = text.split("\n")
    return "\n".join(lines[1:]) if lines and lines[0].startswith("# ") else text


def demote(text: str) -> str:
    """'## ' 제목을 한 단계 내려 페이지 구조에 맞춘다."""
    return re.sub(r"^(#{1,5}) ", lambda m: "#" + m.group(1) + " ", text, flags=re.MULTILINE)


def episode_rows(cfg: ProjectConfig) -> list[EpisodeRow]:
    rows: list[EpisodeRow] = []
    for e in cfg.episodes:
        path = cfg.path(e.file)
        if not path.exists():
            rows.append(EpisodeRow(e.label, e.title, e.status, e.file, None, "파일 없음", 0))
            continue
        rep = check_file(path, cfg)
        issues = len(rep.hygiene) + len(rep.quotes) + len(rep.ellipsis) + len(rep.scene_breaks) + len(rep.over_patterns)
        verdict = rep.length_verdict.split(":")[0]
        ss = rep.short_sentences
        rows.append(
            EpisodeRow(
                e.label, e.title, e.status, e.file, rep.length.muble_estimate, verdict, issues,
                len(ss.runs) if ss else None, ss.ratio if ss else 0.0, bool(ss and ss.over),
            )
        )
    return rows


def checklist_files(cfg: ProjectConfig) -> list[Path]:
    """reviews/의 체크리스트. 파일 이름 앞 번호의 회차가 이미 원고 확정이면 지난 것이라 뺀다."""
    rdir = cfg.path("reviews")
    if not rdir.exists():
        return []
    confirmed = {e.no for e in cfg.confirmed_episodes()}
    files = []
    for p in rdir.glob("*체크리스트*.md"):
        m = re.match(r"(\d+)", p.name)
        if m and int(m.group(1)) in confirmed:
            continue
        files.append(p)
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


WORKLOG_NAME = "작업_로그.md"
WORKLOG_SHOW = 5


def recent_worklog(cfg: ProjectConfig, n: int = WORKLOG_SHOW) -> tuple[str, int]:
    """작업 로그의 최근 n개 항목(최신이 위)과 전체 항목 수. 항목은 '## '로 시작."""
    path = cfg.path(WORKLOG_NAME)
    if not path.exists():
        return "", 0
    chunks = re.split(r"(?m)^(?=## )", read_text(path))
    entries = [c.strip() for c in chunks if c.startswith("## ")]
    return "\n\n".join(reversed(entries[-n:])), len(entries)


def count_open_boxes(text: str) -> int:
    return len(re.findall(r"^\s*- \[ \]", text, flags=re.MULTILINE))


def section(sec_id: str, title: str, body_html: str, open_: bool = False, badge: str = "") -> str:
    b = f' <span class="badge">{html.escape(badge)}</span>' if badge else ""
    return (
        f'<details id="{sec_id}"{" open" if open_ else ""}><summary><h2>{html.escape(title)}{b}</h2></summary>'
        f'<div class="body">{body_html}</div></details>'
    )


def episodes_table(rows: list[EpisodeRow], platform: str) -> str:
    head = f"<tr><th>회차</th><th>제목</th><th>상태</th><th>{html.escape(platform or '플랫폼')} 추정</th><th>분량</th><th>검수 경고</th><th>단문 몰림</th><th>파일</th></tr>"
    body = []
    for r in rows:
        cls = "ok" if r.status == "원고 확정" else "draft"
        warn = f'<span class="warn">{r.issues}</span>' if r.issues else "0"
        chars = f"{r.platform_chars:,}" if r.platform_chars is not None else "—"
        short = "—" if r.short_runs is None else f"{r.short_runs}곳 · {r.short_ratio:.0%}"
        if r.short_over:
            short = f'<span class="warn">{short}</span>'
        body.append(
            f'<tr class="{cls}"><td>{r.label}</td><td>{html.escape(r.title)}</td><td>{html.escape(r.status)}</td>'
            f"<td class=num>{chars}</td><td>{html.escape(r.verdict)}</td><td class=num>{warn}</td><td class=num>{short}</td>"
            f"<td><code>{html.escape(r.file)}</code></td></tr>"
        )
    return f'<div class="scroll"><table>{head}{"".join(body)}</table></div>'


CSS = """
:root{--bg:#fbfaf7;--fg:#1f1d1a;--muted:#6b665e;--card:#ffffff;--line:#e6e1d8;--accent:#2f6f5e;--warn:#b5452c;--draft:#8a6d1f;--ok:#2f6f5e}
@media (prefers-color-scheme:dark){:root{--bg:#161513;--fg:#ebe7e0;--muted:#a39d93;--card:#1f1e1b;--line:#34312c;--accent:#7cc4ad;--warn:#f08a6c;--draft:#e0c065;--ok:#7cc4ad}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.65 -apple-system,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 64px}
header h1{font-size:1.5rem;margin:.2rem 0}header p{color:var(--muted);margin:.2rem 0;font-size:.9rem}
nav{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);margin-bottom:12px;display:flex;gap:6px;flex-wrap:wrap;z-index:2}
nav a{color:var(--accent);text-decoration:none;font-size:.85rem;padding:3px 9px;border:1px solid var(--line);border-radius:999px;background:var(--card)}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;padding:0 16px}
summary{cursor:pointer;list-style:none}summary::-webkit-details-marker{display:none}
summary h2{display:inline-block;font-size:1.1rem;margin:.8rem 0}summary h2::before{content:"▸ ";color:var(--muted)}details[open] summary h2::before{content:"▾ "}
.body{padding-bottom:12px;overflow-wrap:anywhere}.body h3{font-size:1rem;margin:1.2rem 0 .4rem}.body h4{font-size:.95rem}
.badge{font-size:.75rem;background:var(--warn);color:#fff;border-radius:999px;padding:1px 8px;margin-left:6px;vertical-align:middle}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}td.num{text-align:right;white-space:nowrap}
tr.draft td:nth-child(3){color:var(--draft)}tr.ok td:nth-child(3){color:var(--ok)}.warn{color:var(--warn);font-weight:700}
code{font-size:.85em;background:rgba(127,127,127,.12);padding:1px 4px;border-radius:4px}
blockquote{margin:.5rem 0;padding:.2rem .8rem;border-left:3px solid var(--line);color:var(--muted)}
li{margin:.15rem 0}footer{color:var(--muted);font-size:.8rem;margin-top:24px}
"""


def build_html(cfg: ProjectConfig, stamp: str | None = None) -> str:
    stamp = stamp or datetime.now().strftime("%Y-%m-%d %H:%M")
    handoff = cfg.path("HANDOFF.md")
    pending = read_section(handoff, "3.")
    decided = read_section(handoff, "2.")
    status_note = read_section(handoff, "1.")
    rows = episode_rows(cfg)

    parts: list[str] = []
    nav: list[tuple[str, str]] = []

    def add(sec_id: str, title: str, md_text: str, open_: bool = False, badge: str = "", raw_html: str = "") -> None:
        if not md_text and not raw_html:
            return
        nav.append((sec_id, title))
        body = raw_html or md_to_html(demote(strip_title(md_text)))
        parts.append(section(sec_id, title, body, open_, badge))

    log_md, log_total = recent_worklog(cfg)
    if log_md:
        shown = min(WORKLOG_SHOW, log_total)
        add("worklog", f"최근 작업 보고 (최근 {shown}개 / 전체 {log_total}개)", log_md, open_=True)
    add("episodes", "회차 현황", "", open_=True, raw_html=episodes_table(rows, cfg.platform))
    if pending:
        n = len(re.findall(r"^\d+\.", pending, flags=re.MULTILINE))
        add("pending", "작가 결정 대기", "\n".join(pending.split("\n")[1:]), open_=True, badge=f"{n}건" if n else "")
    for i, p in enumerate(checklist_files(cfg)):
        text = read_text(p)
        open_n = count_open_boxes(text)
        add(f"check{i}", f"체크리스트 — {p.stem.replace('_', ' ')}", text, open_=(i == 0), badge=f"남은 {open_n}개" if open_n else "")
    add("status", "진행 상황 메모", "\n".join(status_note.split("\n")[1:]))
    add("decided", "작가가 확정한 결정", "\n".join(decided.split("\n")[1:]))
    for sec_id, title, rel in [
        ("loops", "복선·미해결 목록", "memory/open_loops.md"),
        ("timeline", "시간선", "memory/timeline.md"),
        ("verify", "설정 검증 목록", "설정_검증_목록.md"),
    ]:
        path = cfg.path(rel)
        if path.exists():
            add(sec_id, title, read_text(path))

    nav_html = "".join(f'<a href="#{i}">{html.escape(t)}</a>' for i, t in nav)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(cfg.title)} 대시보드</title><style>{CSS}</style></head>
<body><main>
<header><h1>「{html.escape(cfg.title)}」 작업 대시보드</h1>
<p>생성 {stamp} · StoryForge <code>python -m tools.dashboard</code> · 원본은 작품 폴더의 md 문서(이 페이지는 생성물)</p></header>
<nav>{nav_html}</nav>
{"".join(parts)}
<footer>링크가 아닌 생성 시점의 사본입니다. 내용이 바뀌면 다시 생성하세요.</footer>
</main>
<script>document.querySelectorAll('nav a').forEach(a=>a.addEventListener('click',()=>{{const d=document.querySelector(a.getAttribute('href'));if(d)d.open=true;}}));</script>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="작품 대시보드(HTML) 생성")
    parser.add_argument("--project", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="출력 경로(기본: <작품>/dashboard.html)")
    parser.add_argument("--open", action="store_true", help="생성 후 브라우저로 열기")
    args = parser.parse_args(argv)
    out = setup_output_logging()
    try:
        cfg = load_project(resolve_project(args.project))
        target = args.output or cfg.path("dashboard.html")
        target.write_text(build_html(cfg), encoding="utf-8", newline="\n")
        out.info(f"{target} 생성")
        if args.open:
            webbrowser.open(target.resolve().as_uri())
    except (OSError, ValueError) as e:
        logger.error("대시보드 생성 실패: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
