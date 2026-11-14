"""새 작품 폴더 만들기: 설정 파일·문서 틀·빈 기억 색인·세션용 CLAUDE.md·git 저장소.

사용: python -m tools.new_novel my_novel --title "내 작품" [--platform 노벨피아] [--no-git]
작품 폴더는 기본으로 storyforge/novels/<이름>/ 에 만든다. 이미 있으면 아무것도 덮어쓰지 않고 실패한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

from tools.codex_worker import ensure_workspace
from tools.project import NOVELS_DIR, STORYFORGE_ROOT, load_project, setup_output_logging

logger = logging.getLogger(__name__)

RULES_DOC = "defaults/작가_작업규칙.md"


def config_json(title: str, platform: str) -> dict:
    """storyforge.json 기본값(작가의 노벨피아·뮤블 기준)."""
    return {
        "title": title,
        "platform": platform,
        "pov": "[미정]",
        "length": {"basis": "공백 제외", "platform_min": 3000, "target_min": 3500, "target_max": 4000, "muble_ratio": 0.914},
        "notation": {
            "pairs": {"대사": ['"', '"'], "속말": ["'", "'"]},
            "line_prefixes": [],
            "ellipsis": "……",
            "scene_break": "＊＊＊",
            "breath_blank_lines": 5,
        },
        "patterns": ["common", "style_patterns.json"],
        "episodes": [],
        "memory_files": ["설정집.md", "회차별_기록.md", "설정_검증_목록.md", "memory/open_loops.md", "memory/timeline.md", "memory/characters.md"],
        "entities": "memory/entities.json",
        "characters": "memory/characters.md",
        "review_rules": "README.md#검토 규칙",
        "agents_extra": [{"title": "공통 작업 규칙(작가)", "file": "../../" + RULES_DOC}],
        "_notes": {"muble_ratio": "작가의 이전 작품 실측값 — 이 작품 실측이 나오면 보정."},
    }


def style_patterns_json() -> dict:
    return {
        "_comment": "이 작품 전용 패턴과 기준선. 공통 패턴(defaults/style_patterns_common.json) 위에 덮어쓴다.",
        "baseline": {
            "_source": "작가 문체 기준선(이전 작품 퇴고본에서 잰 값) — 이 작품 퇴고본이 쌓이면 다시 잰다.",
            "narration_avg_len": 30.0,
            "narration_avg_len_warn": 40.0,
            "multi_sentence_paragraphs_warn": 4,
            "short_sentences": {"max_len": 12, "window": 5, "min_short": 4, "limit": 1},
        },
        "patterns": [],
        "spacing_suspects": [],
    }


def text_files(title: str, name: str, today: str) -> dict[str, str]:
    """작품 폴더에 만들 문서 틀(경로 → 내용)."""
    rel_root = "../.."  # novels/<이름>/ 에서 storyforge 루트까지
    return {
        "CLAUDE.md": f"""# 「{title}」 작업 세션

이 폴더는 StoryForge(`{rel_root}`)의 작품 폴더다. 세션을 열면 아래 순서로 읽는다.

1. **공통 작업 규칙**: `{rel_root}/{RULES_DOC}` — 원고를 고치는 범위, 카드, 분량, 문체 기본값, 사실 확인, 기록 방식. 반드시 먼저 읽는다.
2. 도구 설명: `{rel_root}/CLAUDE.md`(도구 구조·실행법). 작업 순서는 `{rel_root}/.claude/skills/`의 episode-review / episode-confirm / episode-draft 문서를 그대로 따른다.
3. 이 작품: `README.md`(상태 태그·**검토 규칙** — 공통 규칙보다 우선), `storyforge.json`, `설정집.md`, `memory/`, `작업_로그.md` 끝부분.

도구는 storyforge 루트에서 실행한다(이 폴더에서 바로 실행하면 `No module named tools`):
```bash
cd {rel_root} && .venv/Scripts/python -m tools.check_episode novels/{name}/01화_수정.txt
cd {rel_root} && .venv/Scripts/python -m tools.recall --project {name} <검색어>
cd {rel_root} && .venv/Scripts/python -m tools.dashboard --project {name}
cd {rel_root} && .venv/Scripts/python -m tools.sync_agents --project {name}
cd {rel_root} && .venv/Scripts/python -m tools.second_opinion novels/{name}/01화_수정.txt
```
- 이 폴더는 자체 git 저장소(작품 저장소). 원격(GitHub 비공개)은 아직 없음 — 만들 때 비공개·`.env` 미포함 확인.
- 다른 작품의 설정·인물·줄거리는 가져오지 않는다(문체 HOW만).
""",
        "README.md": f"""# 「{title}」 집필 자료

- `설정집.md`: 확정 사실, 기획 중인 설정. `회차별_기록.md`: 각 화에서 공개된 정보와 복선, 후속 주의.
- `설정_검증_목록.md`: 미해결 질문·잠재적 모순. `수정_예정.md`: 앞 회차에서 발견해 나중에 고칠 것.
- `style_profile.md` / `style_patterns.json`: 문체 프로필·자동 검수 패턴.
- `memory/`: entities.json(색인) · open_loops.md(복선) · timeline.md(시간선) · characters.md(인물 현황·비밀 표).
- `storyforge.json`: 회차 목록·상태·분량 기준. `작업_로그.md`: 작업 기록(대시보드 원본).

## 운영 규칙
1. 상태 태그: **[원고 확정]** 작가가 채택한 원고에 나온 사실 / **[설정 확정]** 작가가 정했으나 원고에 아직 없음 / **[기획]** 방향만 논의 / **[후보]** 검토 중인 선택지 / **[인물의 추측]** 작중 인물의 추측·주장 / **[미정]** / 초안 출처는 ⚠.
2. 공통 작업 규칙은 `{rel_root}/{RULES_DOC}`. 아래 '검토 규칙'이 그보다 우선한다.

## 검토 규칙
> 이 작품에만 적용되는 검토 제약. StoryForge의 검토 명령과 교차 검토(Codex)가 이 절을 읽는다.
1. **미정 사항 단정 금지**: 작가가 정하지 않은 설정(이름, 핵심 미스터리의 정답, 세계 규칙)을 사실로 쓰지 않는다.
2. (작품 고유 규칙 — 용어·호칭·인물·세계 규칙을 정해지는 대로 추가)
""",
        "설정집.md": f"# 「{title}」 설정집\n\n> 기준: {today}. 태그는 README 운영 규칙.\n\n## 1. 작품 개요\n- 가제: 「{title}」 [설정 확정]\n- 장르·분위기: [미정]\n- 주인공: [미정]\n\n## 2. 세계\n\n## 3. 인물\n\n## 4. 용어\n",
        "회차별_기록.md": f"# 「{title}」 회차별 기록\n\n> 회차를 확정할 때마다 절을 추가한다(상태·분량, 시점, 사건, 새로 확정된 사실, [인물의 추측], 복선, 후속 주의).\n",
        "설정_검증_목록.md": f"# 설정 검증 목록\n\n> 미해결 질문·잠재적 모순·작성 전 체크리스트.\n\n## 미해결\n",
        "수정_예정.md": "# 수정 예정\n\n> 앞 회차에서 발견했지만 지금 고치지 않는 것. 전체 재검토 때 한꺼번에 고친다.\n",
        "작업_로그.md": f"# 작업 로그\n\n## {today} — 작품 폴더 생성\n- 한 일: `tools.new_novel`로 폴더·문서 틀 생성. 공통 규칙 `{RULES_DOC}`.\n- 작가 확인 필요: 장르·주인공·시점·연재 계획.\n",
        "style_profile.md": f"# 「{title}」 문체 프로필\n\n## 0. 요약\n- 공통 문체 기본값은 `{rel_root}/{RULES_DOC}` §5.\n- (이 작품만의 문체 — 시점, 톤, 대사 기호, 개그 결 — 를 정해지는 대로)\n",
        "memory/open_loops.md": "# 복선·미해결 목록 (Open Loops)\n\n> 회차를 확정할 때마다 새 복선 추가 / 진전 기록 / 회수 시 상태 변경.\n> 상태: `열림` · `진행` · `보류` · `회수`.\n\n| ID | 복선 / 미해결 질문 | 처음 | 최근 진전 | 상태 | 회수 방향 (기획) | 관련 |\n|----|------|------|------|------|------|------|\n",
        "memory/timeline.md": "# 시간선\n\n> 회차를 확정할 때마다 한 줄씩 추가한다.\n\n| 회차 | 작중 시점 | 나이 | 장소 | 주요 사건 | 근거 |\n|---|---|---|---|---|---|\n",
        "memory/characters.md": "# 주요 인물 현황\n\n> 회차를 확정할 때마다 등장한 인물의 '현재', 아는 것·모르는 것, 말투, 다음에 확인할 것을 갱신한다.\n\n## 비밀 표 — 누가 무엇을 아는가\n| 비밀 | (인물들) |\n|---|---|\n",
        ".gitignore": "# 생성물(원본 md에서 다시 만들 수 있음)\ndashboard.html\nAGENTS.md\nreviews/*_prompt.md\nreviews/*_rebuttal_prompt.md\ncodex/결과/*_prompt.md\n*_업로드용.txt\n.env\n",
    }


def create_novel(name: str, title: str, platform: str, base: Path = NOVELS_DIR, git: bool = True) -> Path:
    """작품 폴더를 만든다. 이미 있으면 FileExistsError."""
    if not name.replace("_", "").replace("-", "").isascii() or not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"폴더 이름은 영문·숫자·_- 만: {name}")
    root = base / name
    if root.exists():
        raise FileExistsError(f"이미 있는 폴더입니다: {root}")
    (root / "memory").mkdir(parents=True)
    (root / "reviews").mkdir()
    today = date.today().isoformat()

    def dump(rel: str, obj: dict) -> None:
        (root / rel).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    dump("storyforge.json", config_json(title, platform))
    dump("style_patterns.json", style_patterns_json())
    dump("memory/entities.json", {"_comment": "기억 검색(recall)용 인물·사물 색인. 요약과 검색 단서만 둔다.", "entities": []})
    for rel, body in text_files(title, name, today).items():
        (root / rel).write_text(body, encoding="utf-8", newline="\n")
    (root / "reviews" / ".gitkeep").write_text("", encoding="utf-8")
    ensure_workspace(load_project(root))  # Codex 작업공간(codex/) 틀
    if git:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", f"chore: 「{title}」 작품 폴더 생성(tools.new_novel)"], cwd=root, check=True)
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="새 작품 폴더 만들기")
    parser.add_argument("name", help="폴더 이름(영문, 예: my_novel)")
    parser.add_argument("--title", required=True, help="작품 제목(가제)")
    parser.add_argument("--platform", default="노벨피아")
    parser.add_argument("--base", type=Path, default=NOVELS_DIR, help="작품들이 놓일 폴더(기본: storyforge/novels)")
    parser.add_argument("--no-git", action="store_true", help="git 저장소를 만들지 않음")
    args = parser.parse_args(argv)
    out = setup_output_logging()
    try:
        root = create_novel(args.name, args.title, args.platform, base=args.base, git=not args.no_git)
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        logger.error("작품 폴더 생성 실패: %s", e)
        return 1
    out.info(f"작품 폴더 생성: {root}")
    out.info(f"공통 규칙: {STORYFORGE_ROOT / RULES_DOC}")
    out.info(f"이 폴더에서 Claude Code를 열면 CLAUDE.md가 공통 규칙·도구 위치를 안내합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
