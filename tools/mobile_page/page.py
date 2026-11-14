"""모바일 원고·카드 페이지(claude.ai Artifact용 HTML)를 작품 폴더의 `_mobile/`에서 통째로 만든다.

작품 폴더 구조:
    _mobile/page.json          페이지 설정(제목, 출력 파일, 회차 탭, 문서 탭, 기본 탭, 게시 URL)
    _mobile/cards/epN.py       N화 검토 카드(있으면 'N화 검토' 탭). 다시 만들면 그 탭 카드가 통째로 바뀐다.
    _mobile/decisions.py       기획·설정 결정 카드(있으면 '고를 것' 탭)
    _mobile/fixes/epN.json     Claude가 바로 고친 것 기록(fix_guard)
    _mobile/db_sync/epN.json   페이지 db(drafts/epN)에 넣을 원고(생성물, git 제외)
    _mobile/<html>             생성된 페이지(이 파일을 Artifact로 게시)

페이지 db 문서: drafts/epN {text, savedAt, base} · choices/epN-<기준커밋> {카드번호: 고른 번호} · cardx/epN-<기준커밋> {notes: {카드번호: 작가 메모}, custom: {카드번호: [작가가 쓴 선택지 글 | null(지움)]}} — 작가 선택지의 번호는 기존 선택지 수 + 순서 · choices/<결정키> {picks, notes}.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.project import ProjectConfig, load_project

logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent / "assets"
MOBILE_DIR = "_mobile"
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">\n'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Gowun+Batang:wght@400;700'
         '&family=IBM+Plex+Sans+KR:wght@400;500;600&display=swap">\n')


def esc(s: str, quote: bool = False) -> str:
    return html.escape(s, quote=quote)


def blk(s: str) -> str:
    return esc(s).replace("\n", "<br>")


# ── 페이지 설정 ─────────────────────────────────────────────────────────────

@dataclass
class PageSpec:
    title: str
    html: str = "page.html"
    url: str = ""
    episodes: list[str] = field(default_factory=list)
    current: str = ""  # 기본 탭 패널 id(예: "e1", "r1", "dec")
    docs: list[dict[str, str]] = field(default_factory=list)  # [{label, file}]
    files: dict[str, str] = field(default_factory=dict)  # 회차 파일 덮어쓰기 {"1": "01화 v2.txt"}
    labels: dict[str, str] = field(default_factory=dict)  # 탭 이름 덮어쓰기 {"0v2": "프롤로그 v2"}
    decision_key: str = "dec-1"

    @classmethod
    def load(cls, root: Path) -> "PageSpec":
        p = root / MOBILE_DIR / "page.json"
        if not p.exists():
            raise FileNotFoundError(f"{p} 가 없습니다. 먼저 init 하세요.")
        raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def save(self, root: Path) -> None:
        d = root / MOBILE_DIR
        d.mkdir(exist_ok=True)
        (d / "page.json").write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def init_page(root: Path, title: str, docs: list[str] | None = None) -> PageSpec:
    """작품 폴더에 `_mobile/` 틀을 만든다. 이미 있으면 그대로 읽어 돌려준다."""
    d = root / MOBILE_DIR
    if (d / "page.json").exists():
        return PageSpec.load(root)
    cfg = load_project(root)
    spec = PageSpec(title=title, episodes=[str(e.no) for e in cfg.episodes],
                    docs=[{"label": Path(f).stem, "file": f} for f in (docs or [])])
    spec.current = f"e{spec.episodes[-1]}" if spec.episodes else ""
    spec.save(root)
    (d / "cards").mkdir(exist_ok=True)
    gi = root / ".gitignore"
    cur = gi.read_text(encoding="utf-8") if gi.exists() else ""
    add = [x for x in (f"{MOBILE_DIR}/db_sync/", f"{MOBILE_DIR}/build_state.json") if x not in cur.splitlines()]
    if add:
        gi.write_text(cur + ("" if cur.endswith("\n") or not cur else "\n")
                      + "# 모바일 페이지 생성물(db 동기화 파일·빌드 상태)\n" + "".join(x + "\n" for x in add), encoding="utf-8")
    return spec


# ── 원고 ────────────────────────────────────────────────────────────────────

def episode_file(cfg: ProjectConfig, spec: PageSpec, n: str) -> str:
    if n in spec.files:
        return spec.files[n]
    for e in cfg.episodes:
        if str(e.no) == n:
            return e.file
    raise KeyError(f"storyforge.json에 {n}화가 없습니다.")


def episode_label(cfg: ProjectConfig, n: str, spec: PageSpec | None = None) -> str:
    if spec is not None and n in spec.labels:
        return spec.labels[n]
    for e in cfg.episodes:
        if str(e.no) == n:
            return e.label
    return f"{n}화"


def git_rev(root: Path, rel: str) -> str:
    """파일의 마지막 커밋(짧은 해시). 커밋 뒤에 바뀌었으면 '+'를 붙인다(게시 전에 커밋하라는 신호)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h", "--", rel],
                           capture_output=True, text=True, encoding="utf-8")
        rev = r.stdout.strip() or "new"
        d = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", rel],
                           capture_output=True, text=True, encoding="utf-8")
        return rev + ("+" if d.stdout.strip() else "")
    except OSError:
        return "nogit"


def notation_classes(cfg: ProjectConfig) -> dict[str, Any]:
    """대사 기호 → 원고 탭 글자 색 클래스. 대사는 기본색, 속말은 흐리게, 그 밖의 쌍(『』 등)은 강조색."""
    m: dict[str, Any] = {}
    for name, (o, _) in cfg.notation.pairs.items():
        m[o] = "speech" if name == "대사" else "thought" if name == "속말" else "special"
    m["__scene"] = cfg.notation.scene_break or "＊＊＊"
    m["__breath"] = 3
    return m


def render_ms(text: str, classes: dict[str, Any]) -> str:
    """원고 → 읽기용 HTML(editor.js의 render와 같은 규칙)."""
    out: list[str] = []
    blank = 0
    scene = classes.get("__scene", "＊＊＊")
    breath = int(classes.get("__breath", 3))
    openers = [(o, c) for o, c in classes.items() if not o.startswith("__")]
    for ln in text.split("\n"):
        if not ln.strip():
            blank += 1
            continue
        if blank >= breath:
            out.append('<div class="breath" aria-hidden="true">· · ·</div>')
        elif blank >= 1:
            out.append('<div class="gap"></div>')
        blank = 0
        s = ln.strip()
        if s == scene:
            out.append(f'<div class="scene">{esc(scene)}</div>')
            continue
        c = next((cl for o, cl in openers if s.startswith(o)), "")
        out.append(f'<p class="{c}">{esc(s)}</p>' if c else f"<p>{esc(s)}</p>")
    return "\n".join(out)


def episode_panel(n: str, label: str, fn: str, text: str, rev: str, classes: dict[str, Any]) -> str:
    return (f'<main id="p-e{n}" class="panel" hidden>\n'
            f'<header style="display:grid;gap:6px"><span class="eyebrow">{esc(label)} · {esc(fn)} · 기준 {rev}</span><h1>{esc(label)} 원고</h1>\n'
            '<p class="note">편집을 눌러 바로 고칠 수 있습니다. 저장하면 이 페이지에 보관되고, Claude가 읽어 가서 파일에 반영합니다.</p></header>\n'
            f'<div class="card" data-ep-editor="{n}" data-base="{rev}">\n<div class="row">'
            '<button type="button" class="edbtn ed-toggle">편집</button>'
            '<button type="button" class="edbtn ed-save" hidden>저장</button>'
            '<button type="button" class="edbtn ed-copy" hidden>전체 복사</button>'
            '<button type="button" class="edbtn ed-reset" hidden>원본으로 되돌리기</button></div>\n'
            f'<p class="note edst">원본(파일 기준 {rev})을 보고 있습니다.</p>\n'
            f'<textarea class="edtext" hidden spellcheck="false" aria-label="{esc(label, True)} 원고 편집">{esc(text)}</textarea>\n'
            f'<div class="ms" style="display:grid">{render_ms(text, classes)}</div>\n</div>\n</main>\n')


# ── 검토 카드 ────────────────────────────────────────────────────────────────

Opt = tuple[str, bool, str, list[tuple[str, str]]]


def card_api(ms: str, ep: str) -> dict[str, Any]:
    """카드 파일(cards/epN.py)에서 쓰는 도우미들."""
    blocks = ms.split("\n\n")

    def B(head: str) -> str:
        hits = [b for b in blocks if b.startswith(head)]
        if len(hits) != 1:
            raise ValueError(f"'{head}'로 시작하는 문단이 {len(hits)}개입니다.")
        return hits[0]

    def opt(label: str, rec: bool, orig: str, new: str) -> Opt:
        return (label, rec, new, [(orig, new)])

    def one(no: int, title: str, where: str, orig: str, opts: list[Opt], note: str,
            again: str | None = None) -> dict[str, Any]:
        # 작가가 넘긴(놓친) 논리·문장 오류를 다시 올릴 때: 제목 앞 '(두 번째)' 또는 again="…" → 빨간 테두리
        if again is None and title.startswith("(두 번째)"):
            again, title = "놓친 오류 · 두 번째", title[len("(두 번째)"):].strip()
        return dict(id=no, ep=ep, title=title, where=where, orig=orig, opts=opts, note=note, again=again)

    def lst(head: str, xs: list[str]) -> str:
        return f'<div class="card"><h3>{esc(head)}</h3>' + "".join(f'<p class="note">· {esc(x)}</p>' for x in xs) + "</div>"

    return {"MS": ms, "B": B, "opt": opt, "one": one, "lst": lst, "esc": esc}


def card_html(c: dict[str, Any]) -> str:
    opts = "".join(f'<div class="blk new"><b>{esc(l)}' + (' <span class="pill ok">추천</span>' if rec else "")
                   + f'</b><span class="ms-inline">{blk(tx)}</span></div>' for l, rec, tx, _ in c["opts"])
    # 고른 것 없음 = 보류(choices에 키 없음), 원본 유지 = -1(결정됨). 작가 요청 2026-11-07, 4장 도구에 다시 옮김 2026-11-14.
    btns = ('<button type="button" class="edbtn ch" data-k="h">보류</button>'
            '<button type="button" class="edbtn ch" data-k="-1">원본 유지</button>') + "".join(
        f'<button type="button" class="edbtn ch" data-k="{i}">{esc(o[0].split(":")[0])}</button>' for i, o in enumerate(c["opts"]))
    again = c.get("again")
    cls = "card again" if again else "card"
    tag = f'<span class="again-tag">{esc(again)}</span> ' if again else ""
    return (f'<div class="{cls}" data-card="{c["id"]}" data-ep="{c["ep"]}"><h3>{tag}{c["id"]}. {esc(c["title"])}</h3>'
            f'<p class="note">{esc(c["where"])}</p><div class="pair">'
            f'<div class="blk old"><b>원본</b><span class="ms-inline">{blk(c["orig"])}</span></div>{opts}</div>'
            f'<p class="note">{esc(c["note"])}</p><div class="row">{btns}<span class="note chst"></span></div></div>')


def load_cards(path: Path, ms: str, ep: str) -> dict[str, Any]:
    g: dict[str, Any] = card_api(ms, ep)
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), g)  # 작품 폴더의 카드 정의(Claude가 쓴 파일)
    return g


def review_panel(n: str, label: str, rev: str, g: dict[str, Any], ms: str) -> tuple[str, dict[str, Any]]:
    cards = g.get("cards", [])
    data: dict[str, Any] = {}
    for c in cards:
        out = []
        for _, _, _, edits in c["opts"]:
            pairs = []
            for f, r in edits:
                cnt = ms.count(f)
                if cnt != 1:
                    raise ValueError(f"카드 {c['id']}: 원본이 원고에 {cnt}번 나옵니다(딱 한 번이어야 함): {f[:40]!r}")
                pairs.append({"find": f, "repl": r})
            out.append(pairs)
        data[str(c["id"])] = out
    extra = "".join(g.get("EXTRA", []))
    body = (f'<main id="p-r{n}" class="panel" hidden>\n<header style="display:grid;gap:6px">'
            f'<span class="eyebrow">{esc(label)} · 검토 · 기준 {rev}</span><h1>{esc(g.get("TITLE", label + " 검토"))}</h1>'
            f'<p class="note">{esc(g.get("SUB", ""))}</p></header>\n'
            + "\n".join(card_html(c) for c in cards) + extra
            + f'<script type="application/json" id="rev-data-{n}">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
            + "</script>\n</main>\n")
    return body, data


# ── 결정 카드 · 문서 탭 ──────────────────────────────────────────────────────

def decision_panel(path: Path, key: str) -> str:
    g: dict[str, Any] = {"esc": esc}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), g)

    def dec_card(k: str, title: str, why: str, opts: list[tuple[str, bool, str, str]]) -> str:
        btns = "".join(
            f'<button type="button" class="opt" data-k="{ok}" aria-pressed="false">'
            f'<span class="opt-h"><b>{esc(ok)}</b> {esc(lab)}{" <span class=\"pill ok\">추천</span>" if rec else ""}</span>'
            f'<span class="opt-b">{esc(desc)}</span></button>' for ok, rec, lab, desc in opts)
        return (f'<article class="card dec" data-key="{esc(k, True)}"><h3>{esc(title)}</h3><p class="why">{esc(why)}</p>'
                f'<div class="opts">{btns}</div><label class="memo-l" for="memo-{esc(k, True)}">메모</label>'
                f'<textarea id="memo-{esc(k, True)}" class="memo" rows="2" placeholder="다른 생각이나 이름 후보를 적어 주세요"></textarea></article>')

    return (f'<main id="p-dec" class="panel" data-key="{esc(key, True)}" hidden>\n<header style="display:grid;gap:6px">'
            f'<span class="eyebrow">고를 것</span><h1>{esc(g.get("TITLE", "고를 것"))}</h1>'
            f'<p class="note">{esc(g.get("SUB", "하나씩 눌러 고르고, 다른 생각은 메모에 적은 뒤 맨 아래 저장을 눌러 주세요."))}</p></header>\n'
            + "".join(g.get("EXTRA", []))
            + "\n".join(dec_card(*d) for d in g.get("DECS", []))
            + '\n<div class="savebar"><button type="button" id="dec-save" class="save">저장</button>'
              '<span id="dec-note" class="note" role="status"></span></div>\n</main>\n')


def _inline(s: str) -> str:
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def md_to_html(text: str) -> str:
    """기획·설정 문서용 간단 마크다운(제목, 표, 인용, 목록, 굵게, 코드)."""
    out: list[str] = []
    lines = text.split("\n")
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            flush(); i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            flush()
            lvl = min(len(m.group(1)) + 1, 4)
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1; continue
        if ln.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            h = "<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in rows[0]) + "</tr>"
            b = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
            out.append(f'<div class="tbl"><table><thead>{h}</thead><tbody>{b}</tbody></table></div>')
            continue
        if ln.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].startswith(">"):
                q.append(lines[i].lstrip(">").strip()); i += 1
            out.append("<blockquote>" + "<br>".join(_inline(x) for x in q if x) + "</blockquote>")
            continue
        if re.match(r"^\s*(-|\d+\.)\s", ln):
            flush()
            items: list[tuple[int, bool, str]] = []
            while i < len(lines) and re.match(r"^\s*(-|\d+\.)\s", lines[i]):
                mm = re.match(r"^(\s*)(-|\d+\.)\s+(.*)", lines[i])
                assert mm
                items.append((len(mm.group(1)) // 2, mm.group(2) != "-", mm.group(3)))
                i += 1
            stack: list[str] = []
            buf = ""
            for depth, ordered, txt in items:
                tag = "ol" if ordered else "ul"
                while len(stack) > depth + 1:
                    buf += f"</li></{stack.pop()}>"
                if len(stack) == depth + 1:
                    buf += "</li>"
                while len(stack) < depth + 1:
                    stack.append(tag); buf += f"<{tag}>"
                buf += f"<li>{_inline(txt)}"
            while stack:
                buf += f"</li></{stack.pop()}>"
            out.append(buf)
            continue
        para.append(ln.strip()); i += 1
    flush()
    return "\n".join(out)


def doc_panel(i: int, label: str, rel: str, text: str) -> str:
    return (f'<main id="p-d{i}" class="panel md" hidden>\n<p class="note">문서 · <code>{esc(rel)}</code></p>\n'
            + md_to_html(text) + "\n</main>\n")


# ── 전체 페이지 ──────────────────────────────────────────────────────────────

@dataclass
class BuildResult:
    path: Path
    revs: dict[str, str]
    changed: list[str]  # 지난 빌드 뒤 기준 커밋이 바뀐 회차 → db drafts/epN 동기화 필요
    unclean: list[str]  # 커밋 안 된 원고(기준에 '+')
    cards: dict[str, list[int]]


def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def build_page(root: Path, current: str | None = None) -> BuildResult:
    cfg = load_project(root)
    spec = PageSpec.load(root)
    if current:
        spec.current = current
        spec.save(root)
    mdir = root / MOBILE_DIR
    classes = notation_classes(cfg)
    tabs: list[tuple[str, str]] = []
    panels: list[str] = []
    revs: dict[str, str] = {}
    keys: dict[str, str] = {}
    cards_out: dict[str, list[int]] = {}
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sync = mdir / "db_sync"
    sync.mkdir(exist_ok=True)
    for n in reversed(spec.episodes):  # 최근 회차가 앞
        fn = episode_file(cfg, spec, n)
        text = (root / fn).read_text(encoding="utf-8")
        rev = git_rev(root, fn)
        revs[n] = rev
        label = episode_label(cfg, n, spec)
        cf = mdir / "cards" / f"ep{n}.py"
        if cf.exists():
            g = load_cards(cf, text, n)
            body, data = review_panel(n, label, rev, g, text)
            tabs.append((f"p-r{n}", f"{label} 검토"))
            panels.append(body)
            keys[n] = f"ep{n}-{rev}"
            cards_out[n] = [int(k) for k in data]
        tabs.append((f"p-e{n}", f"{label} 원고"))
        panels.append(episode_panel(n, label, fn, text, rev, classes))
        (sync / f"ep{n}.json").write_text(json.dumps({"text": text, "savedAt": now, "base": rev}, ensure_ascii=False), encoding="utf-8")
    dec = mdir / "decisions.py"
    if dec.exists():
        tabs.append(("p-dec", "고를 것"))
        panels.append(decision_panel(dec, spec.decision_key))
    for i, d in enumerate(spec.docs):
        tabs.append((f"p-d{i}", d["label"]))
        panels.append(doc_panel(i, d["label"], d["file"], (root / d["file"]).read_text(encoding="utf-8")))

    ids = [t[0] for t in tabs]
    cur = f"p-{spec.current}" if spec.current and f"p-{spec.current}" in ids else (ids[0] if ids else "")
    page_rev = hashlib.sha1(json.dumps([revs, sorted(keys.values()), ids]).encode()).hexdigest()[:8]
    nav = "".join(f'<button type="button" class="tab" aria-selected="{"true" if p == cur else "false"}" data-panel="{p}">{esc(lab)}</button>'
                  for p, lab in tabs)
    if cur:  # 기본 탭만 보이게(스크립트 전에도)
        panels = [re.sub(rf'^(<main id="{cur}"[^>]*?) hidden>', r"\1>", x, count=1) for x in panels]
    slug = re.sub(r"[^a-z0-9_-]", "", root.name.lower()) or "page"
    page = (f"<title>{esc(spec.title)}</title>\n"
            '<meta name="claude:viewport-fit-sides" content="cover">\n' + FONTS + _asset("style.css")
            + f'<script>document.body.dataset.page="{slug}";document.body.dataset.current="{cur}";document.body.dataset.pageRev="{page_rev}"</script>\n'
            + '<nav aria-label="탭">' + nav + "</nav>\n" + "".join(panels)
            + '<script type="application/json" id="notation-data">' + json.dumps(classes, ensure_ascii=False) + "</script>\n"
            + '<script type="application/json" id="rev-keys">' + json.dumps(keys) + "</script>\n"
            + _asset("editor.js") + _asset("cards.js") + _asset("tabs.js"))
    out = mdir / spec.html
    out.write_text(page, encoding="utf-8", newline="\n")

    state_p = mdir / "build_state.json"
    prev: dict[str, str] = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {}
    changed = [n for n, r in revs.items() if prev.get(n) != r]
    state_p.write_text(json.dumps(revs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    unclean = [n for n, r in revs.items() if r.endswith("+")]
    return BuildResult(out, revs, changed, unclean, cards_out)


# ── 바로 고친 것 되돌림 감시(fix_guard) ──────────────────────────────────────

def _fix_path(root: Path, n: str) -> Path:
    d = root / MOBILE_DIR / "fixes"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"ep{n}.json"


def fix_load(root: Path, n: str) -> list[dict[str, str]]:
    p = _fix_path(root, n)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def fix_add(root: Path, n: str, old: str, new: str, note: str = "") -> int:
    xs = fix_load(root, n)
    xs.append({"old": old, "new": new, "note": note})
    _fix_path(root, n).write_text(json.dumps(xs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(xs)


def fix_check(root: Path, n: str, text: str) -> list[dict[str, str]]:
    """옛 문구가 다시 나타난 기록(작가 저장본이 옛 판 위에서 고쳐졌다는 신호)."""
    return [x for x in fix_load(root, n) if x["old"] in text]

