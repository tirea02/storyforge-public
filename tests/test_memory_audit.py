from pathlib import Path

from tools.memory_audit import audit, default_docs, fragments, load_manuscripts, main
from tools.project import load_project


def _setup(proj: Path) -> None:
    (proj / "01.txt").write_text('"안녕, 친구야."\n『기록했습니다. 출처는 요정의 진술입니다.』\n', encoding="utf-8")
    (proj / "02.txt").write_text('"바람이 제일 세."\n', encoding="utf-8")
    (proj / "03.txt").write_text('"초안에만 있는 말."\n', encoding="utf-8")  # 초안 회차는 대조하지 않음


def test_verdicts(mini_project: Path) -> None:
    _setup(mini_project)
    manus = load_manuscripts(load_project(mini_project))
    doc = (
        "- 1화: '안녕, 친구야' 인사\n"
        "- 1화: 바람 '바람이 제일 세.'\n"
        "- 2화: 『숟가락은 나무입니다』\n"
        "- 1화: 『기록했습니다… 요정의 진술입니다』\n"
        "- 3화: '초안에만 있는 말'\n"
        "- 1화: '이름(별명) → 바뀜'\n"
    )
    got = {f.quote: f.verdict for f in audit("doc.md", doc, manus)}
    assert got["안녕, 친구야"] == "맞음"
    assert got["바람이 제일 세."] == "다른 화"
    assert got["숟가락은 나무입니다"] == "근거 없음"
    assert got["기록했습니다… 요정의 진술입니다"] == "맞음"
    assert got["초안에만 있는 말"] == "근거 없음"
    assert "이름(별명) → 바뀜" not in got  # 따옴표가 엉킨 조각은 세지 않음


def test_fragments() -> None:
    assert fragments("안 돼… 검증도 안 된 걸") == ["검증도안된걸"]


def test_default_docs_and_cli(mini_project: Path, tmp_path: Path) -> None:
    _setup(mini_project)
    (mini_project / "설정집.md").write_text("- 1화 '안녕, 친구야'\n", encoding="utf-8")
    (mini_project / "characters").mkdir()
    (mini_project / "characters" / "주인공.md").write_text("- 2화 '바람이 제일 세.'\n", encoding="utf-8")
    docs = default_docs(load_project(mini_project))
    assert "설정집.md" in docs and "characters/주인공.md" in docs
    out = tmp_path / "r.md"
    assert main(["--project", str(mini_project), "-o", str(out)]) == 0
    assert "| characters/주인공.md | 1 | 1 | 0 | 0 |" in out.read_text(encoding="utf-8")


def test_stale_checks() -> None:
    from tools.memory_audit import stale_checks

    doc = (
        "# 문서\n> 기준: 3화 확정\n"
        "- ⚠5화 초안: 무언가\n"
        "- ⚠12화 초안: 아직 안 씀\n"
        "- 8화에서 공개 예정\n"
        "- 9화 대사는 수정_예정\n"
        "| L01 | 질문 | 2화 | 7화: 진전 | 열림 | 방향 | 인물 |\n"
        "| L02 | 질문 | 2화 | — | 진행 — 메모 | 방향 | 인물 |\n"
    )
    out = stale_checks("doc.md", doc, latest=10)
    text = "\n".join(out)
    assert "L3 ⚠ 표시인데" in text and "L4" not in text  # 12화는 아직 확정 전
    assert "8화는 이미 확정됨" in text
    assert "'열림'인데 7화 진전" in text
    assert "L02 상태 칸" in text
    assert "머리말 '기준: 3화'" in text
    assert "수정_예정" not in text
    skipped = stale_checks("doc.md", doc, latest=10, skip_plan=True)
    assert not any("예정" in s or "⚠" in s for s in skipped)


def test_tangled_quotes_skipped() -> None:
    from tools.memory_audit import tangled

    assert tangled(" 으로 삼음. 할머니 말에서 ")
    assert tangled(", 『저와 이어져』, 도윤 ")
    assert not tangled("바람이 제일 세.")
