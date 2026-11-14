# 「등대지기 수습일지」 작업 세션

이 폴더는 StoryForge(`../..`)의 작품 폴더다. 세션을 열면 아래 순서로 읽는다.

1. **공통 작업 규칙**: `../../defaults/작가_작업규칙.md` — 원고를 고치는 범위, 카드, 분량, 문체 기본값, 사실 확인, 기록 방식. 반드시 먼저 읽는다.
2. 도구 설명: `../../CLAUDE.md`(도구 구조·실행법). 작업 순서는 `../../.claude/skills/`의 episode-review / episode-confirm / episode-draft 문서를 그대로 따른다.
3. 이 작품: `README.md`(상태 태그·**검토 규칙** — 공통 규칙보다 우선), `storyforge.json`, `설정집.md`, `memory/`, `작업_로그.md` 끝부분.

도구는 storyforge 루트에서 실행한다(이 폴더에서 바로 실행하면 `No module named tools`):
```bash
cd ../.. && .venv/Scripts/python -m tools.check_episode novels/demo_novel/01화_수정.txt
cd ../.. && .venv/Scripts/python -m tools.recall --project demo_novel <검색어>
cd ../.. && .venv/Scripts/python -m tools.dashboard --project demo_novel
cd ../.. && .venv/Scripts/python -m tools.sync_agents --project demo_novel
cd ../.. && .venv/Scripts/python -m tools.second_opinion novels/demo_novel/01화_수정.txt
```
- 이 폴더는 자체 git 저장소(작품 저장소). 원격(GitHub 비공개)은 아직 없음 — 만들 때 비공개·`.env` 미포함 확인.
- 다른 작품의 설정·인물·줄거리는 가져오지 않는다(문체 HOW만).
