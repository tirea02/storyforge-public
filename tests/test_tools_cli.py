from __future__ import annotations

from pathlib import Path

from tools.check_episode import check_file, render
from tools.clean_text import clean
from tools.project import find_project_root, load_project
from tools.recall import build_packs, detect_entities, load_entities, render as render_recall, resolve_queries


def test_load_project_and_confirmed(mini_project: Path) -> None:
    cfg = load_project(mini_project)
    assert cfg.title == "테스트 소설"
    assert [e.no for e in cfg.confirmed_episodes()] == [1, 2]
    assert find_project_root(mini_project / "01.txt") == mini_project


def test_check_file_flags_patterns_and_length(mini_project: Path) -> None:
    ep = mini_project / "draft.txt"
    ep.write_text("그때였다.\n\n잠깐. 잠깐. 잠깐.\n\n그녀가 웃었다.\n", encoding="utf-8")
    rep = check_file(ep)
    over = {p.pattern_id for p in rep.over_patterns}
    assert over == {"then", "wait"}
    assert "그녀" in render(rep)
    assert rep.length.muble_estimate == round(rep.length.no_space * 0.5)


def test_clean_removes_invisible_and_trims_without_touching_text() -> None:
    res = clean("​ 첫  줄 \n\n 둘\t")
    assert res.text == "첫 줄\n\n둘"
    assert res.removed_invisible == 1
    assert res.replaced_space_like == 1
    assert res.double_spaces == 1


def test_clean_keep_nbsp() -> None:
    assert " " in clean("가 나", keep_nbsp=True).text


def test_recall_uses_confirmed_only_by_default(mini_project: Path) -> None:
    cfg = load_project(mini_project)
    ents = load_entities(cfg)
    targets, free = resolve_queries(["요정"], ents)
    assert [e.id for e in targets] == ["green"]
    assert free == []
    packs = build_packs(cfg, targets, free, quotes_per=5, include_drafts=False)
    quotes = packs[0].quotes
    assert [q.episode.no for q in quotes] == [2]
    mem_texts = [m.text for m in packs[0].memory]
    assert any("[원고 확정]" in t for t in mem_texts)
    assert any("L05" in t for t in mem_texts)
    assert not any("글머리표 아님" in t for t in mem_texts)


def test_recall_include_drafts_and_recent_order(mini_project: Path) -> None:
    cfg = load_project(mini_project)
    targets, _ = resolve_queries(["등불새"], load_entities(cfg))
    packs = build_packs(cfg, targets, [], quotes_per=5, include_drafts=True)
    assert [q.episode.no for q in packs[0].quotes] == [3, 2]


def test_recall_free_keyword_and_render(mini_project: Path) -> None:
    cfg = load_project(mini_project)
    targets, free = resolve_queries(["오라"], load_entities(cfg))
    assert targets == [] and free == ["오라"]
    packs = build_packs(cfg, targets, free, quotes_per=3, include_drafts=False)
    text = render_recall(cfg, packs, max_chars=3000, tail=None)
    assert "오라의 정체" in text
    assert "\n\n\n" not in text


def test_detect_entities_from_text(mini_project: Path) -> None:
    ents = load_entities(load_project(mini_project))
    found = detect_entities("할머니와 할머니, 그리고 등불새", ents, min_hits=2)
    assert [e.id for e, _ in found] == ["mother"]


def test_normalize_ellipsis() -> None:
    from tools.clean_text import normalize_ellipsis

    text, n = normalize_ellipsis("아... 그래…… 음…", "……")
    assert text == "아…… 그래…… 음……"
    assert n == 2


def test_normalize_quotes_both_ways() -> None:
    from tools.clean_text import normalize_quotes

    src = "'잠깐, 내 이름이 '그만 울어'라는 거야?'\n\"어머!\""
    curly, n = normalize_quotes(src, "curly")
    assert curly == "‘잠깐, 내 이름이 ‘그만 울어’라는 거야?’\n“어머!”"
    assert n == 6
    back, m = normalize_quotes(curly, "straight")
    assert back == src and m == 6


def test_dashboard_builds_sections(mini_project: Path) -> None:
    from tools.dashboard import build_html

    (mini_project / "HANDOFF.md").write_text(
        "# 인계\n## 1. 현황\n진행 중\n## 2. 결정\n- 분량\n## 3. 결정 대기\n1. 이름\n2. 속도\n", encoding="utf-8"
    )
    (mini_project / "reviews").mkdir()
    (mini_project / "reviews" / "03_작가_체크리스트.md").write_text("# 체크\n- [ ] 남음\n- [x] 끝\n", encoding="utf-8")
    (mini_project / "reviews" / "02_작가_체크리스트.md").write_text("# 지난 체크\n- [ ] 옛것\n", encoding="utf-8")
    page = build_html(load_project(mini_project), stamp="T")
    assert "<!doctype html>" in page and "테스트 소설" in page
    assert "회차 현황" in page and "첫 화" in page
    assert "작가 결정 대기" in page and "2건" in page
    assert "남은 1개" in page and "☐ 남음" in page and "☑ 끝" in page
    assert "옛것" not in page  # 확정된 회차(2화)의 체크리스트는 뺀다
    assert "복선·미해결 목록" in page
    assert "최근 작업 보고" not in page  # 로그가 없으면 섹션 없음
    (mini_project / "작업_로그.md").write_text(
        "# 로그\n## 첫 작업\n- 하나\n## 둘째 작업\n- 둘\n", encoding="utf-8"
    )
    page = build_html(load_project(mini_project), stamp="T")
    assert "최근 작업 보고 (최근 2개 / 전체 2개)" in page
    assert page.index("둘째 작업") < page.index("첫 작업")  # 최신이 위
