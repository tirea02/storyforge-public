from pathlib import Path

from tools.codex_worker import build_prompt, citation_report, ensure_workspace, main, verify_citations
from tools.project import load_project


def _eps(proj: Path) -> None:
    (proj / "01.txt").write_text("첫 줄\n\"안녕, 친구야.\"\n셋째 줄\n", encoding="utf-8")
    (proj / "02.txt").write_text("\"바람이 제일 세.\"\n", encoding="utf-8")
    (proj / "03.txt").write_text("초안 첫 줄\n", encoding="utf-8")


def test_workspace_created_and_note_kept(mini_project: Path) -> None:
    cfg = load_project(mini_project)
    ws = ensure_workspace(cfg)
    assert (ws / "결과").is_dir()
    agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
    assert "테스트 소설" in agents and "codex/" in agents and "{title}" not in agents
    note = ws / "작업노트.md"
    note.write_text("내 메모", encoding="utf-8")
    ensure_workspace(cfg)
    assert note.read_text(encoding="utf-8") == "내 메모"  # 작업노트는 덮어쓰지 않음


def test_build_prompt_paths(mini_project: Path) -> None:
    _eps(mini_project)
    cfg = load_project(mini_project)
    prompt, name = build_prompt(cfg, "대조", "3")
    assert name == "03화_대조.md"
    assert "../03.txt" in prompt and "../02.txt" in prompt  # 직전 확정 회차와 대조
    assert "초안" in prompt
    prompt, name = build_prompt(cfg, "사실확인", "3", "03_v2.txt")  # 같은 회차의 다른 판
    assert name == "03화_v2_사실확인.md" and "../03_v2.txt" in prompt
    prompt, name = build_prompt(cfg, "기억점검", "reviews/기억점검/r.md")
    assert name == "기억점검_r.md" and "../reviews/기억점검/r.md" in prompt


def test_verify_citations(mini_project: Path) -> None:
    _eps(mini_project)
    cfg = load_project(mini_project)
    text = (
        "| 1 | 근거: 1화 L2 「안녕, 친구야.」 |\n"
        "| 2 | 근거: 2화 L40 「바람이 제일 세.」 |\n"
        "| 3 | 근거: 1화 L1 「지어낸 대사입니다」 |\n"
        "| 4 | 근거: 3화 L1 「초안 첫 줄」 |\n"
        "| 5 | 근거: 1화 L3줄 「셋째 줄」 |\n"  # 'L3줄'로 써도 읽음
    )
    v = [c.verdict for c in verify_citations(text, cfg)]
    assert v == ["맞음", "줄 다름", "원문에 없음", "초안 회차", "맞음"]
    rep = citation_report(verify_citations(text, cfg))
    assert "맞음 2" in rep and "원문에 없음" in rep and "실제 L1" in rep


def test_cli_dry_run_and_recheck(mini_project: Path) -> None:
    _eps(mini_project)
    assert main(["--project", str(mini_project), "사실확인", "3", "--dry-run"]) == 0
    assert (mini_project / "codex" / "결과" / "03화_사실확인_prompt.md").exists()
    res = mini_project / "codex" / "결과" / "03화_사실확인.md"
    res.write_text("| 1 | 근거: 1화 L2 「안녕, 친구야.」 |\n", encoding="utf-8")
    assert main(["--project", str(mini_project), "근거대조", "codex/결과/03화_사실확인.md"]) == 0
    assert main(["--project", str(mini_project), "근거대조", "codex/결과/03화_사실확인.md"]) == 0  # 두 번 돌려도 한 번만 붙음
    assert res.read_text(encoding="utf-8").count("근거 자동 대조") == 1
