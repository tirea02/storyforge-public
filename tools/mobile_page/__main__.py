"""모바일 원고·카드 페이지 CLI.

    python -m tools.mobile_page init  --project my_novel --title "내 작품" [--doc 설정집.md ...]
    python -m tools.mobile_page build --project my_novel [--current e1|r1|dec|d0]
    python -m tools.mobile_page ep    --project my_novel 0v2 --file "프롤로그 v2.txt" --label "프롤로그 v2"  # 회차 탭 추가
    python -m tools.mobile_page guard add   --project ... 1 "옛 문구" "새 문구" "이유"
    python -m tools.mobile_page guard check --project ... 1 [원고 파일 | db에서 받은 json]

build 뒤 할 일(순서 중요): ① '!! db 동기화'로 나온 회차마다 ArtifactData set drafts/epN ← _mobile/db_sync/epN.json (if_version)
② Artifact publish(_mobile/<html>, page.json의 url). 게시 URL은 page.json "url"에 적어 둔다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.mobile_page.page import MOBILE_DIR, PageSpec, build_page, fix_add, fix_check, fix_load, init_page
from tools.project import resolve_project, setup_output_logging


def quote_check(root: Path) -> list[tuple[str, str]]:
    """페이지에 올라가는 회차 원고마다 대사 기호 짝 문제(게시 전에 고칠 것)."""
    from tools.mobile_page.page import episode_file
    from tools.project import load_project
    from tools.textstats import quote_issues

    cfg = load_project(root)
    spec = PageSpec.load(root)
    found: list[tuple[str, str]] = []
    for n in spec.episodes:
        path = root / episode_file(cfg, spec, n)
        if path.exists():
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            found += [(n, i.render()) for i in quote_issues(text, cfg.notation)]
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.mobile_page", description="모바일 원고·카드 페이지 만들기")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="작품 폴더에 _mobile/ 틀 만들기")
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--doc", action="append", default=[], help="문서 탭으로 넣을 md(작품 폴더 기준)")
    p_build = sub.add_parser("build", help="페이지 HTML 다시 만들기")
    p_build.add_argument("--current", help="기본 탭: e<N> 원고, r<N> 검토, dec 고를 것, d<i> 문서")
    p_ep = sub.add_parser("ep", help="회차 탭 추가")
    p_ep.add_argument("n")
    p_ep.add_argument("--file", help="storyforge.json과 다른 파일을 쓸 때")
    p_ep.add_argument("--label", help="탭 이름(기본: storyforge.json의 회차 이름)")
    p_guard = sub.add_parser("guard", help="바로 고친 것 기록·되돌림 확인")
    p_guard.add_argument("action", choices=["add", "check", "list"])
    p_guard.add_argument("n")
    p_guard.add_argument("args", nargs="*")
    for p in (p_init, p_build, p_ep, p_guard):
        p.add_argument("--project", type=Path)
    args = ap.parse_args(argv)
    out = setup_output_logging()
    try:
        root = resolve_project(args.project)
        if args.cmd == "init":
            spec = init_page(root, args.title, args.doc)
            out.info(f"{root / MOBILE_DIR / 'page.json'} — 회차 {spec.episodes}, 문서 {[d['file'] for d in spec.docs]}")
            return 0
        if args.cmd == "ep":
            spec = PageSpec.load(root)
            if args.n not in spec.episodes:
                spec.episodes.append(args.n)
            if args.file:
                spec.files[args.n] = args.file
            if args.label:
                spec.labels[args.n] = args.label
            spec.current = f"e{args.n}"
            spec.save(root)
            args.cmd, args.current = "build", None
        if args.cmd == "build":
            r = build_page(root, args.current)
            out.info(f"ok {r.path} · 기준 {r.revs} · 카드 {r.cards}")
            for n in r.unclean:
                out.info(f"!! {n}화 원고가 커밋되지 않았습니다(기준에 '+'). 커밋한 뒤 다시 build 하세요.")
            for n, issue in quote_check(root):
                out.info(f"!! {n}화 대사 기호 짝: {issue}")
            for n in r.changed:
                out.info(f"!! db 동기화 필요(게시 전에): ArtifactData set drafts/ep{n} ← {root / MOBILE_DIR / 'db_sync' / f'ep{n}.json'} (if_version)")
            spec = PageSpec.load(root)
            out.info(f"게시: Artifact publish {r.path}" + (f" (url {spec.url})" if spec.url else " — 첫 게시 뒤 page.json \"url\"에 주소를 적어 두세요"))
            return 0
        if args.cmd == "guard":
            if args.action == "add":
                if len(args.args) < 2:
                    ap.error("guard add N 옛문구 새문구 [이유]")
                k = fix_add(root, args.n, args.args[0], args.args[1], args.args[2] if len(args.args) > 2 else "")
                out.info(f"기록 {k}건")
                return 0
            if args.action == "list":
                for x in fix_load(root, args.n):
                    out.info(f"'{x['old']}' → '{x['new']}' {x.get('note', '')}")
                return 0
            src = Path(args.args[0]) if args.args else None
            if src is None:
                spec = PageSpec.load(root)
                from tools.mobile_page.page import episode_file
                from tools.project import load_project
                src = root / episode_file(load_project(root), spec, args.n)
            elif not src.is_absolute() and not src.exists():
                src = root / src
            raw = src.read_text(encoding="utf-8")
            text = json.loads(raw).get("text", raw) if src.suffix == ".json" else raw
            bad = fix_check(root, args.n, text)
            for x in bad:
                out.info(f"되돌아감: '{x['old']}' (고친 말: '{x['new']}') {x.get('note', '')}")
            out.info(f"{len(bad)}건 / 기록 {len(fix_load(root, args.n))}건")
            return 1 if bad else 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        out.error(f"오류: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
