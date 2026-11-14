from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.new_novel import create_novel
from tools.project import load_patterns, load_project


def test_create_novel_makes_loadable_project(tmp_path: Path) -> None:
    root = create_novel("my_novel", "테스트 신작", "노벨피아", base=tmp_path, git=False)
    cfg = load_project(root)
    assert cfg.title == "테스트 신작"
    assert cfg.length.target_min == 3500
    assert (root / "CLAUDE.md").read_text(encoding="utf-8").count("작가_작업규칙.md") >= 1
    assert "## 검토 규칙" in (root / "README.md").read_text(encoding="utf-8")
    ents = json.loads((root / "memory" / "entities.json").read_text(encoding="utf-8"))
    assert ents["entities"] == []
    pats = load_patterns(cfg)
    assert pats["baseline"]["narration_avg_len"] == 30.0
    assert (root / "codex" / "작업노트.md").exists() and (root / "codex" / "결과").is_dir()


def test_create_novel_refuses_existing_and_bad_name(tmp_path: Path) -> None:
    create_novel("a", "가", "노벨피아", base=tmp_path, git=False)
    with pytest.raises(FileExistsError):
        create_novel("a", "가", "노벨피아", base=tmp_path, git=False)
    with pytest.raises(ValueError):
        create_novel("한글폴더", "가", "노벨피아", base=tmp_path, git=False)
