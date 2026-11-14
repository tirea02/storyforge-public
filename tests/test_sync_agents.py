from __future__ import annotations

import os
import time
from pathlib import Path

from tools import second_opinion, sync_agents
from tools.project import load_project


def _docs(proj: Path) -> None:
    (proj / "README.md").write_text(
        "# 작품\n## 운영 규칙\n1. 태그 정의.\n## 검토 규칙\n1. AI는 시야 밖을 못 본다.\n", encoding="utf-8"
    )
    (proj / "HANDOFF.md").write_text(
        "# 인계\n## 1. 현황\n생략\n## 2. 작가가 확정한 결정\n- 분량은 공백 제외.\n## 3. 결정 대기\n- 이름 미정.\n## 4. 작업 방식\n- 제안만.\n",
        encoding="utf-8",
    )
    (proj / "style_profile.md").write_text(
        "# 문체\n## 0. 요약\n짧게.\n## 1. 따라 할 것\n비공개\n## 2. 피할 것\n그때였다.\n", encoding="utf-8"
    )
    (proj / "memory" / "timeline.md").write_text("# 시간선\n| 1화 | 첫날 |\n## 고정 앵커\n- 앵커", encoding="utf-8")


def test_build_collects_sections_from_sources(mini_project: Path) -> None:
    _docs(mini_project)
    text, dropped = sync_agents.build(load_project(mini_project), stamp="T", inline=True)
    assert dropped == []
    for needle in ["너의 역할 (Codex)", "AI는 시야 밖을 못 본다.", "분량은 공백 제외.", "이름 미정.", "짧게.", "그때였다.", "| 1화 | 첫 화 | 원고 확정 |", "**등불새**", "| L05 | 등불새의 정체 |", "- 앵커"]:
        assert needle in text, needle
    assert "비공개" not in text and "생략" not in text
    assert "제안만." not in text  # Claude 작업 방식(§4)은 Codex 지침에서 제외
    assert "AI: 『…』" not in text and "AI 『…』" in text


def test_build_drops_optional_sections_over_limit(mini_project: Path) -> None:
    _docs(mini_project)
    cfg = load_project(mini_project)
    full, _ = sync_agents.build(cfg, stamp="T", inline=True)
    text, dropped = sync_agents.build(cfg, max_bytes=len(full.encode("utf-8")) - 10, stamp="T", inline=True)
    assert dropped and "역할" not in "".join(dropped)
    assert "분량은 공백 제외." in text  # 필수 섹션은 유지


def test_sync_writes_file_and_staleness(mini_project: Path) -> None:
    _docs(mini_project)
    cfg = load_project(mini_project)
    assert sync_agents.is_stale(cfg)
    target, size, _ = sync_agents.sync(cfg)
    assert target.name == "AGENTS.md" and size > 0
    assert not sync_agents.is_stale(cfg)
    later = time.time() + 5
    os.utime(mini_project / "HANDOFF.md", (later, later))
    assert sync_agents.is_stale(cfg)


def test_lean_prompt_omits_shared_guidance(mini_project: Path) -> None:
    _docs(mini_project)
    cfg = load_project(mini_project)
    full = second_opinion.build_prompt(mini_project / "02.txt", cfg)
    lean = second_opinion.build_prompt(mini_project / "02.txt", cfg, lean=True)
    assert "AI는 시야 밖을 못 본다." in full and "AI는 시야 밖을 못 본다." not in lean
    assert "AGENTS.md 참고" in lean
    assert "직전 회차 마지막 장면" in lean and "# 원고: 02.txt" in lean
    assert "먼저 직접 열어 읽을 파일" in lean and "먼저 직접 열어 읽을 파일" not in full


def test_dry_run_syncs_agents(mini_project: Path) -> None:
    _docs(mini_project)
    assert second_opinion.main([str(mini_project / "02.txt"), "--dry-run"]) == 0
    assert (mini_project / "AGENTS.md").exists()


def test_characters_section_included_and_dropped_last(mini_project: Path) -> None:
    import json as _json

    _docs(mini_project)
    cfg_path = mini_project / "storyforge.json"
    raw = _json.loads(cfg_path.read_text(encoding="utf-8"))
    raw["characters"] = "memory/characters.md"
    cfg_path.write_text(_json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (mini_project / "memory" / "characters.md").write_text("# 인물 현황\n## 도윤\n- 현재: 다섯 살, 언덕\n", encoding="utf-8")
    cfg = load_project(mini_project)
    text, dropped = sync_agents.build(cfg, stamp="T", inline=True)
    assert dropped == [] and "## 주요 인물 현황" in text and "현재: 다섯 살, 언덕" in text
    assert "# 인물 현황" not in text  # 원본 제목 줄은 뺀다
    # 한도가 빠듯하면 다른 선택 섹션부터 빠지고 인물 현황은 남는다
    small, dropped2 = sync_agents.build(cfg, max_bytes=len(text.encode("utf-8")) - 10, stamp="T", inline=True)
    assert dropped2 and "주요 인물 현황" not in dropped2 and "현재: 다섯 살, 언덕" in small


def test_default_lists_reference_docs_instead_of_contents(mini_project: Path) -> None:
    import json as _json

    _docs(mini_project)
    cfg_path = mini_project / "storyforge.json"
    raw = _json.loads(cfg_path.read_text(encoding="utf-8"))
    raw["characters"] = "memory/characters.md"
    raw["agents_extra"] = [{"title": "마법 설정 대장", "file": "설정_마법.md"}]
    cfg_path.write_text(_json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (mini_project / "memory" / "characters.md").write_text("# 인물\n- 현재: 다섯 살\n", encoding="utf-8")
    (mini_project / "설정_마법.md").write_text("# 마법\n- 오라는 실재한다.\n", encoding="utf-8")
    cfg = load_project(mini_project)
    text, dropped = sync_agents.build(cfg, stamp="T")
    assert dropped == [] and "분량은 공백 제외." in text  # 핵심 지침은 그대로
    assert "## 참고 문서 (직접 열어 읽을 것)" in text
    assert "| `설정_마법.md` | 마법 설정 대장 — **매 검토 필수** |" in text
    assert "오라는 실재한다." not in text and "현재: 다섯 살" not in text  # 내용은 담지 않는다
    assert "`memory/timeline.md`" in text and "읽은 파일:" in text
    assert sync_agents.must_read(cfg) == ["memory/characters.md", "설정_마법.md"]
    block = second_opinion.must_read_block(mini_project / "02.txt", cfg)
    assert "- `설정_마법.md`" in block and "- `01.txt`" in block  # 직전 회차 원고 포함
    assert "must" not in block and "읽은 파일:" in second_opinion.build_prompt(mini_project / "02.txt", cfg, lean=True)


def test_agents_extra_reference_docs(mini_project: Path) -> None:
    import json as _json

    _docs(mini_project)
    cfg_path = mini_project / "storyforge.json"
    raw = _json.loads(cfg_path.read_text(encoding="utf-8"))
    raw["agents_extra"] = [{"title": "마법 설정 대장", "file": "설정_마법.md"}]
    cfg_path.write_text(_json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (mini_project / "설정_마법.md").write_text("# 마법\n## 1. 오라\n- 오라는 실재한다.\n", encoding="utf-8")
    text, dropped = sync_agents.build(load_project(mini_project), stamp="T", inline=True)
    assert dropped == [] and "## 마법 설정 대장" in text and "오라는 실재한다." in text
    assert "### 1. 오라" in text  # 문서 안 제목은 한 단계 내려간다
