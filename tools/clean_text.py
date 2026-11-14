"""업로드용 서식 정리.

보이지 않는 문자 제거, 줄 앞뒤 공백 제거, 문장 안 연속 공백을 한 칸으로.
문장·줄바꿈 구조는 바꾸지 않는다. 기본은 '<원본>_업로드용.txt' 사본을 만든다.

사용법:
    python -m tools.clean_text novels/<작품>/<원고>.txt
    python -m tools.clean_text 파일 --inplace      # 원본 덮어쓰기(주의)
    python -m tools.clean_text 파일 --keep-nbsp    # NBSP는 일반 공백으로 바꾸지 않음
    python -m tools.clean_text 파일 --ellipsis ……  # 줄임표를 한 표기로 통일(…… / … / ...)
    python -m tools.clean_text 파일 --quotes straight  # 뮤블에서 고친 둥근 따옴표(‘’ “”)를 곧은 따옴표로
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.project import read_text, setup_output_logging

logger = logging.getLogger(__name__)

REMOVE_CHARS = ("​", "‌", "‍", "﻿")
SPACE_LIKE = (" ", "　")


@dataclass
class CleanResult:
    text: str
    removed_invisible: int
    replaced_space_like: int
    lines_trimmed: int
    double_spaces: int


ELLIPSIS_ANY = re.compile(r"(…+|\.{3,}|‥+)")


def normalize_ellipsis(text: str, style: str) -> tuple[str, int]:
    """줄임표 묶음을 한 표기로. 원래 길이(한 번/두 번)는 따지지 않고 style 하나로 바꾼다."""
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        if m.group(0) != style:
            count += 1
        return style

    return ELLIPSIS_ANY.sub(repl, text), count


CURLY_TO_STRAIGHT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
OPENING_CONTEXT = set(" \t\n([{『「<“‘—-…")


def normalize_quotes(text: str, style: str) -> tuple[str, int]:
    """따옴표 모양 통일. style='straight'(' ") 또는 'curly'(‘’ “”).

    곧은 → 둥근 변환은 앞 글자로 여닫음을 정한다: 줄 처음·공백·여는 괄호 뒤면 여는 기호, 아니면 닫는 기호.
    """
    if style == "straight":
        changed = sum(text.count(c) for c in "‘’“”")
        return text.translate(CURLY_TO_STRAIGHT), changed
    out: list[str] = []
    changed = 0
    for i, ch in enumerate(text):
        if ch in ("'", '"'):
            prev = text[i - 1] if i > 0 else "\n"
            opening = prev in OPENING_CONTEXT
            if ch == "'":
                out.append("‘" if opening else "’")
            else:
                out.append("“" if opening else "”")
            changed += 1
        else:
            out.append(ch)
    return "".join(out), changed


def clean(text: str, keep_nbsp: bool = False) -> CleanResult:
    removed = sum(text.count(c) for c in REMOVE_CHARS)
    for c in REMOVE_CHARS:
        text = text.replace(c, "")
    replaced = 0
    if not keep_nbsp:
        for c in SPACE_LIKE:
            replaced += text.count(c)
            text = text.replace(c, " ")
    out_lines: list[str] = []
    trimmed = 0
    doubles = 0
    for line in text.split("\n"):
        stripped = line.strip(" \t")
        if stripped != line:
            trimmed += 1
        collapsed, n = re.subn(r" {2,}", " ", stripped)
        doubles += n
        out_lines.append(collapsed)
    return CleanResult("\n".join(out_lines), removed, replaced, trimmed, doubles)


def default_output(path: Path) -> Path:
    return path.with_name(f"{path.stem}_업로드용{path.suffix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="업로드용 서식 정리")
    parser.add_argument("file", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="출력 경로(기본: <원본>_업로드용.txt)")
    parser.add_argument("--inplace", action="store_true", help="원본을 덮어씀")
    parser.add_argument("--keep-nbsp", action="store_true")
    parser.add_argument("--ellipsis", choices=["……", "…", "..."], help="줄임표 표기 통일")
    parser.add_argument("--quotes", choices=["straight", "curly"], help="따옴표 모양 통일(곧은 ' \" / 둥근 ‘’ “”)")
    args = parser.parse_args(argv)
    out = setup_output_logging()
    try:
        res = clean(read_text(args.file), keep_nbsp=args.keep_nbsp)
        ellipsis_changed = 0
        if args.ellipsis:
            new_text, ellipsis_changed = normalize_ellipsis(res.text, args.ellipsis)
            res.text = new_text
        quotes_changed = 0
        if args.quotes:
            res.text, quotes_changed = normalize_quotes(res.text, args.quotes)
        target = args.file if args.inplace else (args.output or default_output(args.file))
        target.write_text(res.text, encoding="utf-8", newline="\n")
    except OSError as e:
        logger.error("정리 실패: %s", e)
        return 1
    out.info(
        f"{target} 저장: 보이지 않는 문자 {res.removed_invisible}개 제거, 특수 공백 {res.replaced_space_like}개 치환, "
        f"앞뒤 공백 정리 {res.lines_trimmed}줄, 연속 공백 {res.double_spaces}곳"
        + (f", 줄임표 통일 {ellipsis_changed}곳" if args.ellipsis else "")
        + (f", 따옴표 변환 {quotes_changed}개" if args.quotes else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
