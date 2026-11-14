# StoryForge

**장편 웹소설(200화 이상) 연재를 무너지지 않게 돕는 도구 묶음.** Claude Code 위에서 돌아갑니다.

AI가 대신 쓰는 도구가 아닙니다. **작가가 쓰고, AI는 검토자·기억 관리자 역할**을 맡습니다.

| 핵심 가치 | 하는 일 |
|---|---|
| ① 설정·연속성 유지 | 회차를 확정할 때마다 설정집·복선·인물 현황·시간선을 갱신하고, 기억 검색으로 지난 회차의 근거 문장을 찾아 줍니다. |
| ② 작가 문체 유지 | 'AI 쇠맛'(단언 뒤 뒤집기, '그때였다', 감정 해설 등)을 패턴으로 잡고, 작가 원고는 제안만 합니다. |
| ③ 업로드 전 기계 점검 | 플랫폼 기준 분량, 대사 기호 짝, 숨은 문자, 장면 전환 표기, 띄어쓰기 의심 구간을 점검합니다. |

> 포트폴리오 설명: [`docs/PORTFOLIO.md`](docs/PORTFOLIO.md)

---

## 빠른 시작

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/python

# 데모 작품으로 바로 실행
.venv/Scripts/python -m tools.check_episode examples/demo_novel/01화_수정.txt
.venv/Scripts/python -m tools.recall --project examples/demo_novel 열쇠
.venv/Scripts/python -m tools.memory_audit --project examples/demo_novel

# 테스트
.venv/Scripts/python -m pytest tests/ -v
```

데모 작품 「등대지기 수습일지」는 벨 에포크풍(증기 열차와 갓 들인 전등의 시대) 해안 마을 등대에 수습으로 들어간 주인공의 코즈믹 호러(크툴루 신화풍)입니다. 프롤로그와 1화 원고, 설정집·복선·시간선·인물 현황이 채워져 있어 도구를 바로 돌려 볼 수 있습니다.

### 내 작품 등록
```bash
.venv/Scripts/python -m tools.new_novel my_novel --title "내 작품" --platform 노벨피아
# → novels/my_novel/ 에 설정·문서 틀·세션용 CLAUDE.md·git 저장소 생성
```
`novels/`는 `.gitignore`에 들어 있습니다. 원고는 작가 자산이라 도구 저장소와 분리하고, 작품마다 비공개 저장소로 관리하는 것을 권합니다.

---

## 도구

| 명령 | 역할 |
|---|---|
| `tools.check_episode` | 회차 검수: 분량(플랫폼 환산), 서식, 대사 기호 짝, 문단 호흡, 짧은 단문 몰림, AI 습관 패턴, 띄어쓰기 의심 |
| `tools.clean_text` | 업로드용 서식 정리(사본 생성, 문장은 바꾸지 않음) |
| `tools.recall` | 기억 검색(라이트 RAG): 인물·사물 이름과 별칭 → 설정·복선·원고 인용 묶음 |
| `tools.memory_audit` | 기억 점검: 기억 문서에 따옴표로 인용한 문장이 확정 원고에 실제로 있는지 대조, 낡은 표시 점검 |
| `tools.codex_worker` | 다른 AI(Codex CLI)에게 사실 확인·교차 검토를 맡기고, 결과에 적힌 근거 인용을 원문과 자동 대조 |
| `tools.second_opinion` | Codex 교차 검토(단발형) + 반박 라운드 |
| `tools.sync_agents` | 작품 기억을 요약한 `AGENTS.md`(Codex용 지침) 자동 생성, 크기 한도 관리 |
| `tools.mobile_page` | 휴대폰용 원고·검토 카드 페이지(claude.ai Artifact) 생성, 작가 편집본 동기화, 되돌림 감시 |
| `tools.dashboard` | 작품 대시보드 HTML(회차 현황·결정 대기·복선·시간선) |
| `tools.new_novel` | 새 작품 폴더 생성 |

## 작업 흐름

```
작가 집필/퇴고 ─▶ episode-review(검토) ─▶ 작가 수정 ─▶ episode-confirm(확정·기억 갱신)
                     ▲                                          │
                     └──── episode-draft(샘플, 요청 시) ◀───────┘
              장이 끝나면 memory-dream(기억 전체 점검 → 카드)
```
네 흐름은 Claude Code 스킬(`.claude/skills/`)로 들어 있습니다. 작품 이름은 인자로 받고, 도구와 스킬에 작품 고유 내용을 넣지 않습니다.

## 구조

```
storyforge/
├── tools/            검수·기억·교차 검토·페이지 도구 (python -m tools.<이름>)
├── defaults/         공통 AI 습관 패턴, 공통 작업 규칙, Codex 작업 지침 틀
├── .claude/skills/   episode-review / episode-confirm / episode-draft / memory-dream
├── tests/            pytest
├── examples/         데모 작품
└── novels/           내 작품들 (git 제외)
```
작품마다 다른 것(플랫폼, 분량 기준, 대사 기호, 문체 기준선, 패턴 덮어쓰기, 기억 문서 목록)은 작품 폴더의 `storyforge.json`에만 둡니다.

## 요구 사항
- Python 3.11+
- [Claude Code](https://claude.com/claude-code): 스킬·검토 흐름을 쓸 때
- Codex CLI: 교차 검토를 쓸 때(선택)

문서와 출력은 한국어입니다. 한국 웹소설 연재 환경(공백 제외 글자 수, 플랫폼별 환산 등)을 기준으로 만들었습니다.
