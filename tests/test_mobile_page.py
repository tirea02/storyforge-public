from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.mobile_page.__main__ import main
from tools.mobile_page.page import build_page, fix_add, fix_check, init_page, render_ms

MS = "첫 문단이다.\n\n\"대사.\"\n'속말.'\n\n\n\n\n\n숨 고르기 뒤.\n\n＊＊＊\n\n『특수 대사.』\n"


@pytest.fixture
def novel(tmp_path: Path) -> Path:
    root = tmp_path / "nv"
    root.mkdir()
    (root / "storyforge.json").write_text(json.dumps({
        "title": "테스트",
        "notation": {"pairs": {"대사": ['"', '"'], "속말": ["'", "'"], "시스템": ["『", "』"]}, "scene_break": "＊＊＊"},
        "episodes": [{"no": 0, "title": "프롤", "file": "00화_수정.txt", "status": "초안"},
                     {"no": 1, "title": "하나", "file": "01화_수정.txt", "status": "초안"}],
    }, ensure_ascii=False), encoding="utf-8")
    (root / "00화_수정.txt").write_text("프롤로그.\n", encoding="utf-8")
    (root / "01화_수정.txt").write_text(MS, encoding="utf-8")
    (root / "설정집.md").write_text("# 설정\n\n- **검** 하나\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    return root


def test_init_and_build_page(novel: Path) -> None:
    spec = init_page(novel, "테스트 1장", ["설정집.md"])
    assert spec.episodes == ["0", "1"] and spec.current == "e1"
    assert "_mobile/db_sync/" in (novel / ".gitignore").read_text(encoding="utf-8")
    r = build_page(novel)
    h = r.path.read_text(encoding="utf-8")
    assert h.startswith("<title>테스트 1장</title>")
    assert 'data-panel="p-e1"' in h and 'data-panel="p-e0"' in h and 'data-panel="p-d0"' in h
    assert '<main id="p-e1" class="panel">' in h  # 기본 탭만 보임
    assert '<main id="p-e0" class="panel" hidden>' in h
    assert h.split("<nav")[1].split("</nav>")[0].count('aria-selected="true"') == 1
    assert '<p class="special">『특수 대사.』</p>' in h and "<b>검</b>" in h
    sync = json.loads((novel / "_mobile" / "db_sync" / "ep1.json").read_text(encoding="utf-8"))
    assert sync["text"] == MS and sync["base"] == r.revs["1"]
    assert sorted(r.changed) == ["0", "1"]
    assert build_page(novel).changed == []  # 기준이 그대로면 동기화 알림 없음


def test_render_marks_breath_and_scene() -> None:
    out = render_ms(MS, {'"': "speech", "'": "thought", "__scene": "＊＊＊", "__breath": 3})
    assert '<div class="breath"' in out and '<div class="scene">＊＊＊</div>' in out
    assert '<p class="thought">' in out


def test_cards_tab_and_unique_find(novel: Path) -> None:
    init_page(novel, "t")
    cards = novel / "_mobile" / "cards"
    (cards / "ep1.py").write_text(
        'TITLE = "1화 검토"\nSUB = "요약"\n'
        'O = B("첫 문단")\n'
        'cards = [one(7, "제목", "위치", O, [opt("A: 〔설정〕 설명", True, O, "고친 문단이다.")], "설명")]\n'
        'EXTRA = [lst("참고", ["하나"])]\n', encoding="utf-8")
    r = build_page(novel, current="r1")
    h = r.path.read_text(encoding="utf-8")
    assert r.cards == {"1": [7]}
    assert '<main id="p-r1" class="panel">' in h
    data = json.loads(h.split('id="rev-data-1">')[1].split("</script>")[0])
    assert data["7"] == [[{"find": "첫 문단이다.", "repl": "고친 문단이다."}]]
    assert '"1": "ep1-' in h.split('id="rev-keys">')[1].split("</script>")[0]
    assert '>A</button>' in h  # 버튼 이름은 라벨의 ':' 앞까지
    assert "'cardx/'+KEYS[ep]" in h  # 카드 메모·작가 선택지 저장 문서
    assert '+ 새 선택지' in h and '이 카드에 메모' in h
    (cards / "ep1.py").write_text('O = "\\n\\n"\ncards = [one(8, "t", "w", O, [opt("A", True, O, "x")], "n")]\n', encoding="utf-8")
    with pytest.raises(ValueError):
        build_page(novel)


def test_decisions_tab(novel: Path) -> None:
    init_page(novel, "t")
    (novel / "_mobile" / "decisions.py").write_text(
        'TITLE = "2화 방향"\nDECS = [("k1", "① 질문", "배경", [("A", True, "가", "설명"), ("B", False, "나", "설명")])]\n', encoding="utf-8")
    h = build_page(novel, current="dec").path.read_text(encoding="utf-8")
    assert '<main id="p-dec" class="panel" data-key="dec-1">' in h and 'data-key="k1"' in h


def test_fix_guard(novel: Path) -> None:
    fix_add(novel, "1", "끌", "조각칼", "주인공은 끌 안 씀")
    assert fix_check(novel, "1", "끌을 들었다") and not fix_check(novel, "1", "조각칼을 들었다")


def test_cli_guard_and_build(novel: Path, tmp_path: Path) -> None:
    assert main(["init", "--project", str(novel), "--title", "t"]) == 0
    assert main(["guard", "add", "--project", str(novel), "1", "숨 고르기", "숨고르기"]) == 0
    assert main(["guard", "check", "--project", str(novel), "1"]) == 1
    db = tmp_path / "ep1.json"
    db.write_text(json.dumps({"text": "괜찮다", "base": "x"}), encoding="utf-8")
    assert main(["guard", "check", "--project", str(novel), "1", str(db)]) == 0
    assert main(["ep", "--project", str(novel), "1"]) == 0
    (novel / "v2.txt").write_text("새 판.\n", encoding="utf-8")
    assert main(["ep", "--project", str(novel), "0v2", "--file", "v2.txt", "--label", "프롤로그 v2"]) == 0
    h = (novel / "_mobile" / "page.html").read_text(encoding="utf-8")
    assert '<main id="p-e0v2" class="panel">' in h and ">프롤로그 v2 원고</button>" in h
    assert main(["build", "--project", str(tmp_path / "없음")]) == 2


def test_quote_check_flags_mismatched_marks(novel: Path) -> None:
    from tools.mobile_page.__main__ import quote_check

    init_page(novel, "테스트 1장", [])
    assert quote_check(novel) == []
    (novel / "00화_수정.txt").write_text("『위키 기준입니다.'\r\n", encoding="utf-8")
    found = quote_check(novel)
    assert [n for n, _ in found] == ["0", "0"] and "1행" in found[0][1]


def test_same_card_number_in_two_episodes(novel: Path) -> None:
    init_page(novel, "t")
    cards = novel / "_mobile" / "cards"
    (cards / "ep0.py").write_text('O = "프롤로그."\ncards = [one(1, "t", "w", O, [opt("A", True, O, "영.")], "n")]\n', encoding="utf-8")
    (cards / "ep1.py").write_text('O = B("첫 문단")\ncards = [one(1, "t", "w", O, [opt("A", True, O, "일.")], "n")]\n', encoding="utf-8")
    h = build_page(novel).path.read_text(encoding="utf-8")
    d0 = json.loads(h.split('id="rev-data-0">')[1].split("</script>")[0])
    d1 = json.loads(h.split('id="rev-data-1">')[1].split("</script>")[0])
    assert d0["1"][0][0]["repl"] == "영." and d1["1"][0][0]["repl"] == "일."
    assert 'data-card="1" data-ep="0"' in h and 'data-card="1" data-ep="1"' in h
    assert "(DATA[c.dataset.ep]||{})[c.dataset.card]" in h  # 페이지는 회차별로 찾음(번호만으로 합치면 덮어씀)


def test_card_hold_keep_and_second_time(novel: Path) -> None:
    init_page(novel, "t")
    (novel / "_mobile" / "cards" / "ep1.py").write_text(
        'O = B("첫 문단")\nP = B("숨 고르기")\n'
        'cards = [one(1, "보통", "w", O, [opt("A: 하나", True, O, "일.")], "n"),\n'
        '         one(2, "(두 번째) 놓친 것", "w", P, [opt("A: 둘", True, P, "이.")], "n")]\n', encoding="utf-8")
    h = build_page(novel).path.read_text(encoding="utf-8")
    card1 = h.split('data-card="1" data-ep="1"')[1].split('data-card="2"')[0]
    assert 'data-k="h">보류</button>' in card1 and 'data-k="-1">원본 유지</button>' in card1
    assert 'data-k="0">A</button>' in card1
    assert '<div class="card again" data-card="2"' in h and '<span class="again-tag">놓친 오류 · 두 번째</span> 2. 놓친 것' in h
    assert "c.classList.toggle('held',v===undefined)" in h  # 키 없음 = 보류 표시
