from __future__ import annotations

from tools.project import Notation
from tools.textstats import (
    count_length,
    hygiene_issues,
    is_dialogue,
    paragraph_stats,
    pattern_hits,
    quote_issues,
    rhetorical_triplets,
    spacing_suspects,
)


def test_count_length_excludes_whitespace_and_applies_ratio() -> None:
    rep = count_length("가 나\n다라 ", muble_ratio=0.5)
    assert rep.no_space == 4
    assert rep.with_space == 6
    assert rep.muble_estimate == 2


def test_hygiene_finds_invisible_and_spacing_problems() -> None:
    text = "​첫 줄\n 앞공백\n끝공백 \n   \n두  칸\n정상"
    kinds = {i.kind: i.lines for i in hygiene_issues(text)}
    assert kinds["보이지 않는 문자"] == [1]
    assert kinds["줄 앞 공백"] == [2, 4]
    assert kinds["줄 끝 공백"] == [3]
    assert kinds["공백만 있는 줄"] == [4]
    assert kinds["이중 공백"] == [5]


def test_hygiene_clean_text_has_no_issues() -> None:
    assert hygiene_issues("문장.\n\n'대사.'\n『시스템.』") == []


ELF = Notation(
    pairs={"대사": ('"', '"'), "속말": ("'", "'"), "시스템": ("『", "』"), "시스템창": ("[", "]")},
    line_prefixes=["익명"],
)


def test_quote_issues_ignores_quoted_word_at_line_start() -> None:
    text = "'밥'한테 밀렸다.\n『열린 낫표\n'닫히지 않음"
    found = {i.kind: i.lines for i in quote_issues(text, ELF)}
    assert found["시스템 기호 짝"] == [2]
    assert found["속말 기호 짝"] == [3]


def test_is_dialogue_distinguishes_quoted_narration() -> None:
    assert is_dialogue("'시스템, 봤어?'", ELF)
    assert is_dialogue("『확인했습니다.』", ELF)
    assert is_dialogue("익명 087 : 저거 뭐임?", ELF)
    assert not is_dialogue("'밥'한테 밀린 그날부터 생각했다.", ELF)
    assert not is_dialogue("나는 천장을 봤다.", ELF)
    assert not is_dialogue("『확인했습니다.』")  # 기본 notation에는 『』가 없음


def test_paragraph_stats_counts_multi_sentence_narration() -> None:
    text = "하나. 둘. 셋.\n\n'대사.'\n\n짧다."
    st = paragraph_stats(text)
    assert st.paragraphs == 3
    assert st.narration == 2
    assert st.narration_multi_sentence == 1


def test_pattern_hits_reports_line_numbers_and_limits() -> None:
    pats = [{"id": "then", "label": "그때였다", "regex": "^그때였다\\.$", "limit": 0}]
    hits = pattern_hits("문장.\n그때였다.\n그때였다는 아님", pats)
    assert hits[0].count == 1
    assert hits[0].lines == [2]
    assert hits[0].over


def test_rhetorical_triplets_detects_three_short_questions() -> None:
    text = "마법이 있을까?\n\n드래곤은?\n\n요정은?\n\n평서문."
    assert rhetorical_triplets(text) == [1]
    assert rhetorical_triplets("하나?\n\n둘?\n\n평서문.") == []


def test_spacing_suspects() -> None:
    issues = spacing_suspects("분석한결과 좋다\n정상", ["한결과"])
    assert issues[0].lines == [1]


def test_ellipsis_mix_and_preferred() -> None:
    from tools.textstats import ellipsis_issues, ellipsis_usage

    text = "'…….'\n그것도 아니면... \n음…"
    usage = ellipsis_usage(text)
    assert usage == {"……": [1], "…": [3], "...": [2]}
    mixed = {i.message.split(" ")[0]: i.lines for i in ellipsis_issues(text)}
    assert set(mixed) == {"'…'", "'...'"} or set(mixed) == {"'……'", "'...'"} or len(mixed) == 2
    assert ellipsis_issues("아……\n그래……") == []
    pref = ellipsis_issues("아……\n그래…", preferred="……")
    assert [i.lines for i in pref] == [[2]]


def test_scene_break_issues() -> None:
    from tools.textstats import scene_break_issues

    text = "가.\n\n\n\n나.\n\n***\n\n다.\n\n＊＊＊\n\n라."
    found = {i.message.split(" ")[0]: i.lines for i in scene_break_issues(text, "＊＊＊")}  # 호흡 규칙 없음 → 연속 빈 줄 모두 경고
    assert found["연속"] == [2]  # 연속 빈 줄이 시작되는 줄
    assert found["다른"] == [7]
    assert scene_break_issues(text, None) == []
    assert scene_break_issues("가.\n\n＊＊＊\n\n나.", "＊＊＊") == []


def test_scene_break_with_breath_rule() -> None:
    from tools.textstats import scene_break_issues

    b5 = "\n" * 6  # 빈 줄 5개
    text = "가." + b5 + "나.\n\n\n다.\n\n\n＊＊＊\n\n라."
    found = [i.lines for i in scene_break_issues(text, "＊＊＊", breath=5)]
    assert found == [[8], [11]]  # 빈 줄 2개(8행) 규칙 위반, ＊＊＊ 앞 빈 줄 2개(11행)
    assert scene_break_issues("가." + b5 + "나.", "＊＊＊", breath=5) == []


def test_quote_style_mix_detected() -> None:
    from tools.textstats import quote_style_issues

    text = "'곧은 속말'\n‘뮤블에서 고친 속말’\n\"대사\""
    found = quote_style_issues(text, ELF)
    assert [i.lines for i in found] == [[2]]
    curly_notation = Notation(pairs={"대사": ("“", "”"), "속말": ("‘", "’")})
    assert [i.lines for i in quote_style_issues(text, curly_notation)] == [[1], [3]]


def test_hygiene_catches_extended_invisible_chars() -> None:
    text = "가 나\n다\u0007\n라\n마️\n정상"
    found = {i.message.split(" U+")[0]: i.lines for i in hygiene_issues(text)}
    assert found["특수 공백·구분 문자"] == [1]
    assert found["제어 문자"] == [2]
    assert found["사용자 정의 문자(PUA)"] == [3]
    assert found["변형 선택자"] == [4]


def test_author_note_issues_flags_parentheses_and_or() -> None:
    from tools.textstats import author_note_issues

    text = "본문.\n\"대사\"(과한가?)\n다소 투박했다. or\n정상 줄.\n괄호（전각）"
    found = author_note_issues(text)
    assert [i.lines for i in found] == [[2, 3, 5]]
    assert author_note_issues("story는 normal 하다.\n'or'가 아닌 줄.") == []



def test_short_sentence_runs_marks_dense_staccato() -> None:
    from tools.textstats import short_sentence_runs

    staccato = "쿵.\n\n약탕기가 끓었다.\n\n\"뭐야?\"\n\n약은 산에서 캔다.\n\n고르는 사람은 적다.\n\n나는 아버지를 따라 약장 옆을 천천히 지나 약방 안쪽으로 들어갔다.\n"
    rep = short_sentence_runs(staccato, limit=0)
    assert rep.sentences == 5 and rep.short == 4  # 대사는 세지 않는다
    assert len(rep.runs) == 1 and rep.runs[0].start_line == 1 and rep.over
    assert "쿵." in rep.runs[0].preview

    calm = "나는 아버지를 따라 약장 옆을 천천히 지나갔다.\n\n쿵.\n\n약탕기 끓는 소리에 어깨가 저절로 움츠러들었다.\n\n약은 산에서 캔다.\n\n고르는 사람이 적다는 말이 그제야 이해가 됐다.\n"
    assert short_sentence_runs(calm).runs == []


def test_short_sentence_runs_break_at_scene_mark() -> None:
    from tools.textstats import short_sentence_runs

    text = "쿵.\n\n탁.\n\n＊＊＊\n\n툭.\n\n펑.\n\n그리고 한참 동안 아무도 말을 꺼내지 않았다.\n"
    assert short_sentence_runs(text, window=4, min_short=3).runs == []
