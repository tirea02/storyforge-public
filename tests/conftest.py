"""공통 fixture: 작은 가짜 소설 프로젝트."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def mini_project(tmp_path: Path) -> Path:
    proj = tmp_path / "novel"
    (proj / "memory").mkdir(parents=True)
    (proj / "storyforge.json").write_text(
        json.dumps(
            {
                "title": "테스트 소설",
                "length": {"platform_min": 10, "target_min": 20, "target_max": 200, "muble_ratio": 0.5},
                "episodes": [
                    {"no": 1, "title": "첫 화", "file": "01.txt", "status": "원고 확정"},
                    {"no": 2, "title": "둘째 화", "file": "02.txt", "status": "원고 확정"},
                    {"no": 3, "title": "초안", "file": "03.txt", "status": "초안"},
                ],
                "memory_files": ["설정집.md", "memory/open_loops.md"],
                "platform": "테스트플랫폼",
                "notation": {"pairs": {"대사": ["\"", "\""], "속말": ["'", "'"], "AI": ["『", "』"]}, "line_prefixes": ["익명"]},
                "patterns": ["style_patterns.json"],
                "entities": "memory/entities.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (proj / "01.txt").write_text("할머니가 물방울을 띄웠다.\n\n'시스템, 봤어?'\n『확인했습니다.』\n", encoding="utf-8")
    (proj / "02.txt").write_text("등불새이 손등에 앉았다.\n\n할머니가 웃었다.\n", encoding="utf-8")
    (proj / "03.txt").write_text("초안에서만 등불새이 코에 앉았다.\n", encoding="utf-8")
    (proj / "설정집.md").write_text(
        "# 설정\n## 세계\n- **[원고 확정]** 등불새은 할머니 속삭임에 반응.\n- **[미정]** 오라의 정체.\n본문 문장 등불새(글머리표 아님)\n",
        encoding="utf-8",
    )
    (proj / "memory" / "open_loops.md").write_text(
        "| ID | 복선 |\n|----|----|\n| L05 | 등불새의 정체 |\n", encoding="utf-8"
    )
    (proj / "memory" / "entities.json").write_text(
        json.dumps(
            {
                "entities": [
                    {"id": "green", "name": "등불새", "type": "현상", "aliases": ["등불새", "요정"], "summary": "[원고 확정] 작은 빛"},
                    {"id": "mother", "name": "할머니", "type": "인물", "aliases": ["할머니"], "summary": "[원고 확정] 물 마법"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (proj / "style_patterns.json").write_text(
        json.dumps(
            {
                "baseline": {"narration_avg_len": 30, "narration_avg_len_warn": 40, "multi_sentence_paragraphs_warn": 1},
                "patterns": [
                    {"id": "then", "label": "그때였다", "regex": "^그때였다\\.$", "limit": 0, "advice": "삭제"},
                    {"id": "wait", "label": "잠깐", "regex": "잠깐", "limit": 1},
                    {"id": "she", "label": "그녀", "regex": "그녀", "limit": None},
                ],
                "spacing_suspects": ["한결과"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return proj
