from __future__ import annotations

from pathlib import Path

import pytest

from tools import second_opinion
from tools.project import load_project


def test_build_prompt_contains_sections(mini_project: Path) -> None:
    (mini_project / "style_profile.md").write_text(
        "# 프로필\n## 0. 요약\n짧게 쓴다.\n## 1. 따라 할 것\n생략\n## 2. 피할 것\n그때였다.\n", encoding="utf-8"
    )
    ep = mini_project / "02.txt"
    prompt = second_opinion.build_prompt(ep, load_project(mini_project))
    assert "2차 검토자" in prompt
    assert "짧게 쓴다." in prompt and "그때였다." in prompt
    assert "생략" not in prompt
    assert "   1: 등불새이 손등에 앉았다." in prompt
    assert "기계 점검 결과" in prompt


def test_dry_run_writes_prompt_only(mini_project: Path) -> None:
    code = second_opinion.main([str(mini_project / "01.txt"), "--dry-run"])
    assert code == 0
    assert (mini_project / "reviews" / "01_prompt.md").exists()
    assert not (mini_project / "reviews" / "01_codex.md").exists()


def test_missing_codex_returns_error(mini_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(second_opinion.shutil, "which", lambda _: None)
    code = second_opinion.run_codex("p", mini_project, mini_project / "x.md", ["exec"], timeout=5)
    assert code == 2


def test_prompt_includes_previous_episode_tail(mini_project: Path) -> None:
    (mini_project / "memory" / "timeline.md").write_text("| 1화 | 첫날 |", encoding="utf-8")
    prompt = second_opinion.build_prompt(mini_project / "02.txt", load_project(mini_project))
    assert "직전 회차 마지막 장면 — 1화" in prompt
    assert "> 『확인했습니다.』" in prompt
    assert "| 1화 | 첫날 |" in prompt
