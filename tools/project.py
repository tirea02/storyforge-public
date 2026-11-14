"""작품 설정(storyforge.json) 로딩, 작품 폴더 찾기, 공통 유틸리티."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_NAME = "storyforge.json"
STORYFORGE_ROOT = Path(__file__).resolve().parents[1]
NOVELS_DIR = STORYFORGE_ROOT / "novels"
DEFAULTS_DIR = STORYFORGE_ROOT / "defaults"
ENV_NOVEL = "STORYFORGE_NOVEL"


@dataclass
class Episode:
    no: int
    title: str
    file: str  # 수정본(작업본 = 확정본): NN화_수정.txt
    status: str
    initial: str = ""  # 초기본(처음 만든 판, 고치지 않음): NN화_샘플.txt / NN화_초안.txt

    @property
    def label(self) -> str:
        return "프롤로그" if self.no == 0 else f"{self.no}화"


@dataclass
class LengthRule:
    basis: str = "공백 제외"
    platform_min: int = 3000
    target_min: int = 3500
    target_max: int = 4000
    muble_ratio: float = 1.0


@dataclass
class Notation:
    """대사·속말·특수 대사의 여닫는 기호. 작품마다 다르다."""

    pairs: dict[str, tuple[str, str]] = field(
        default_factory=lambda: {"대사": ('"', '"'), "속말": ("'", "'")}
    )
    line_prefixes: list[str] = field(default_factory=list)
    ellipsis: str | None = None  # 작품이 정한 줄임표 표기("……", "…", "..."). 없으면 섞임만 검사
    scene_break: str | None = None  # 장면 전환 표기(예: "＊＊＊"). 정하면 연속 빈 줄·다른 기호를 검사
    breath_blank_lines: int | None = None  # 같은 장면 안 호흡 구분용 빈 줄 개수(예: 5). 이 개수의 연속 빈 줄은 허용

    @property
    def openers(self) -> tuple[str, ...]:
        return tuple(o for o, _ in self.pairs.values())

    def closer_for(self, opener: str) -> str | None:
        for o, c in self.pairs.values():
            if o == opener:
                return c
        return None

    def asymmetric_pairs(self) -> list[tuple[str, str, str]]:
        """여는 기호와 닫는 기호가 다른 쌍(『』, 「」 등): 개수 비교로 짝 검사."""
        return [(name, o, c) for name, (o, c) in self.pairs.items() if o != c]

    def symmetric_marks(self) -> list[tuple[str, str]]:
        """여닫는 기호가 같은 쌍(" ', 등): 홀수 개수로 짝 검사."""
        return [(name, o) for name, (o, c) in self.pairs.items() if o == c]

    @classmethod
    def from_config(cls, raw: dict[str, Any] | None) -> "Notation":
        if not raw:
            return cls()
        pairs = {name: (v[0], v[1]) for name, v in raw.get("pairs", {}).items()}
        return cls(
            pairs=pairs or cls().pairs,
            line_prefixes=list(raw.get("line_prefixes", [])),
            ellipsis=raw.get("ellipsis"),
            scene_break=raw.get("scene_break"),
            breath_blank_lines=raw.get("breath_blank_lines"),
        )


@dataclass
class ProjectConfig:
    root: Path
    title: str
    episodes: list[Episode]
    length: LengthRule
    notation: Notation = field(default_factory=Notation)
    platform: str = ""
    memory_files: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=lambda: ["common"])
    entities: str = "memory/entities.json"
    characters: str = ""  # 주요 인물 현황 문서(선택). 비어 있으면 쓰지 않는다
    agents_extra: list[dict[str, str]] = field(default_factory=list)  # AGENTS.md에 넣을 참고 문서 [{title, file}]
    audit_skip_plan: list[str] = field(default_factory=list)  # 기억 점검에서 '예정' 점검을 뺄 문서(지난 계획이 역사로 남는 문서)

    def path(self, rel: str) -> Path:
        return self.root / rel

    def confirmed_episodes(self) -> list[Episode]:
        return [e for e in self.episodes if e.status == "원고 확정"]


def load_project(root: Path) -> ProjectConfig:
    """작품 폴더의 storyforge.json을 읽는다."""
    cfg_path = root / CONFIG_NAME
    if not cfg_path.exists():
        raise FileNotFoundError(f"{cfg_path} 가 없습니다. 작품 폴더를 지정하세요.")
    raw: dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))
    episodes = [Episode(**e) for e in raw.get("episodes", [])]
    length = LengthRule(**raw.get("length", {}))
    patterns = raw.get("patterns")
    if patterns is None:  # 구버전 설정 호환
        patterns = ["common", raw.get("style_patterns", "style_patterns.json")]
    return ProjectConfig(
        root=root,
        title=raw.get("title", root.name),
        episodes=sorted(episodes, key=lambda e: e.no),
        length=length,
        notation=Notation.from_config(raw.get("notation")),
        platform=raw.get("platform", ""),
        memory_files=raw.get("memory_files", []),
        patterns=list(patterns),
        entities=raw.get("entities", "memory/entities.json"),
        characters=raw.get("characters", ""),
        agents_extra=list(raw.get("agents_extra", [])),
        audit_skip_plan=list(raw.get("audit_skip_plan", [])),
    )


def find_project_root(start: Path) -> Path | None:
    """start 또는 그 상위 폴더에서 storyforge.json이 있는 폴더를 찾는다."""
    cur = start.resolve()
    if cur.is_file():
        cur = cur.parent
    for p in [cur, *cur.parents]:
        if (p / CONFIG_NAME).exists():
            return p
    return None


def list_novels(novels_dir: Path = NOVELS_DIR) -> list[Path]:
    if not novels_dir.exists():
        return []
    return sorted(p for p in novels_dir.iterdir() if (p / CONFIG_NAME).exists())


def resolve_project(
    explicit: Path | None = None, hint: Path | None = None, novels_dir: Path = NOVELS_DIR
) -> Path:
    """작품 폴더를 정한다.

    우선순위: ① 명시한 경로(작품 폴더 또는 novels/ 아래 이름) ② hint 파일이 속한 작품
    ③ 현재 폴더가 속한 작품 ④ 환경변수 STORYFORGE_NOVEL ⑤ novels/에 작품이 하나뿐이면 그것.
    """
    if explicit is not None:
        for cand in (explicit, novels_dir / explicit):
            if (cand / CONFIG_NAME).exists():
                return cand
        raise FileNotFoundError(f"작품 폴더를 찾지 못했습니다: {explicit} (목록: {', '.join(p.name for p in list_novels(novels_dir)) or '없음'})")
    for start in (hint, Path.cwd()):
        if start is not None:
            root = find_project_root(start)
            if root is not None:
                return root
    env = os.environ.get(ENV_NOVEL)
    if env:
        return resolve_project(Path(env), None, novels_dir)
    novels = list_novels(novels_dir)
    if len(novels) == 1:
        return novels[0]
    names = ", ".join(p.name for p in novels) or "없음"
    raise FileNotFoundError(f"작품을 지정하세요(--project). novels/ 목록: {names}")


def load_patterns(cfg: ProjectConfig, defaults_dir: Path = DEFAULTS_DIR) -> dict[str, Any]:
    """공통 패턴 + 작품 패턴을 합친다.

    작품 패턴 파일의 항목은 같은 id면 덮어쓰고(limit 변경 등), "disabled": true면 끈다.
    baseline은 뒤에 오는 파일이 우선, spacing_suspects는 합집합.
    """
    merged: dict[str, dict[str, Any]] = {}
    baseline: dict[str, Any] = {}
    spacing: list[str] = []
    for ref in cfg.patterns:
        path = defaults_dir / "style_patterns_common.json" if ref == "common" else cfg.path(ref)
        if not path.exists():
            logger.warning("패턴 파일이 없습니다: %s", path)
            continue
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        baseline.update(raw.get("baseline", {}))
        for s in raw.get("spacing_suspects", []):
            if s not in spacing:
                spacing.append(s)
        for p in raw.get("patterns", []):
            pid = p["id"]
            merged[pid] = {**merged.get(pid, {}), **p}
    patterns = [p for p in merged.values() if not p.get("disabled") and "regex" in p]
    return {"baseline": baseline, "patterns": patterns, "spacing_suspects": spacing}


def read_text(path: Path) -> str:
    """UTF-8(BOM 허용)로 읽고 줄바꿈을 LF로 통일한다."""
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_section(path: Path, heading_prefix: str) -> str:
    """마크다운에서 '## <heading_prefix>'로 시작하는 절 하나를 잘라 낸다."""
    if not path.exists():
        return ""
    out: list[str] = []
    take = False
    for line in read_text(path).split("\n"):
        if line.startswith("## "):
            take = line[3:].strip().startswith(heading_prefix)
        if take:
            out.append(line)
    return "\n".join(out).strip()


def setup_output_logging(verbose: bool = False) -> logging.Logger:
    """CLI 보고서를 stdout으로 내보내는 로거. (print 대신 사용)"""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (ValueError, OSError):
            pass
    out = logging.getLogger("storyforge.report")
    out.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    out.addHandler(handler)
    out.setLevel(logging.INFO)
    out.propagate = False
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="[%(levelname)s] %(message)s")
    return out
