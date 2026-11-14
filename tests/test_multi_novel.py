from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.project import Notation, list_novels, load_patterns, load_project, resolve_project
from tools.textstats import is_dialogue, quote_issues


def _make_novel(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True)
    (d / "storyforge.json").write_text(json.dumps({"title": name, "episodes": []}), encoding="utf-8")
    return d


def test_resolve_project_by_name_hint_and_single(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    novels = tmp_path / "novels"
    a = _make_novel(novels, "a")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("STORYFORGE_NOVEL", raising=False)
    assert resolve_project(Path("a"), novels_dir=novels) == a
    assert resolve_project(None, None, novels_dir=novels) == a  # 하나뿐이면 자동
    b = _make_novel(novels, "b")
    (b / "01.txt").write_text("x", encoding="utf-8")
    assert resolve_project(None, b / "01.txt", novels_dir=novels) == b  # 파일 위치로 판별
    with pytest.raises(FileNotFoundError):
        resolve_project(None, None, novels_dir=novels)  # 둘 이상이면 지정 필요
    monkeypatch.setenv("STORYFORGE_NOVEL", "b")
    assert resolve_project(None, None, novels_dir=novels) == b
    assert [p.name for p in list_novels(novels)] == ["a", "b"]


def test_pattern_merge_override_and_disable(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "style_patterns_common.json").write_text(
        json.dumps(
            {
                "baseline": {"narration_avg_len": 30},
                "patterns": [
                    {"id": "wait", "regex": "잠깐", "limit": 3},
                    {"id": "then", "regex": "그때였다", "limit": 0},
                ],
                "spacing_suspects": ["한결과"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    novel = _make_novel(tmp_path, "n")
    cfg_raw = json.loads((novel / "storyforge.json").read_text(encoding="utf-8"))
    cfg_raw["patterns"] = ["common", "mine.json"]
    (novel / "storyforge.json").write_text(json.dumps(cfg_raw), encoding="utf-8")
    (novel / "mine.json").write_text(
        json.dumps(
            {
                "baseline": {"narration_avg_len": 25},
                "patterns": [
                    {"id": "wait", "limit": 10},
                    {"id": "then", "disabled": True},
                    {"id": "own", "regex": "천장", "limit": 2},
                ],
                "spacing_suspects": ["될셈"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    merged = load_patterns(load_project(novel), defaults_dir=defaults)
    by = {p["id"]: p for p in merged["patterns"]}
    assert set(by) == {"wait", "own"}
    assert by["wait"]["limit"] == 10 and by["wait"]["regex"] == "잠깐"
    assert merged["baseline"]["narration_avg_len"] == 25
    assert merged["spacing_suspects"] == ["한결과", "될셈"]


def test_notation_drives_dialogue_and_quotes() -> None:
    corner = Notation(pairs={"대사": ("「", "」")}, line_prefixes=[])
    assert is_dialogue("「안녕.」", corner)
    assert not is_dialogue('"안녕."', corner)  # 이 작품에선 큰따옴표가 대사 기호가 아님
    issues = quote_issues("「열림\n정상", corner)
    assert issues[0].lines == [1]
    assert quote_issues('"홀수', corner) == []


def test_legacy_config_style_patterns_key(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path, "old")
    raw = {"title": "old", "episodes": [], "style_patterns": "sp.json"}
    (novel / "storyforge.json").write_text(json.dumps(raw), encoding="utf-8")
    assert load_project(novel).patterns == ["common", "sp.json"]
