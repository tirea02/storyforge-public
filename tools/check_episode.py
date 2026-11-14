"""회차 원고 검수 보고서.

사용법:
    python -m tools.check_episode novels/<작품>/<원고>.txt
    python -m tools.check_episode novels/<작품>/<원고>.txt --json

원고가 속한 작품 폴더(storyforge.json)를 자동으로 찾아 그 작품의 기준을 적용한다.
검사 항목: 분량(공백 제외·플랫폼 환산), 서식 위생(보이지 않는 문자·공백), 남은 작가 메모(괄호·'or'),
대사 기호 짝(작품 notation), 문단 호흡(기준선 대비), 짧은 단문 몰림(빈도 기록·경계), AI 습관 패턴(공통+작품), 띄어쓰기 의심.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.project import (
    Notation,
    ProjectConfig,
    find_project_root,
    load_patterns,
    load_project,
    read_text,
    setup_output_logging,
)
from tools.textstats import (
    Issue,
    LengthReport,
    author_note_issues,
    ParagraphStats,
    PatternHit,
    count_length,
    ellipsis_issues,
    scene_break_issues,
    hygiene_issues,
    paragraph_stats,
    pattern_hits,
    quote_issues,
    quote_style_issues,
    rhetorical_triplets,
    ShortSentenceReport,
    short_sentence_runs,
    spacing_suspects,
)

logger = logging.getLogger(__name__)


@dataclass
class EpisodeReport:
    file: str
    length: LengthReport
    length_verdict: str
    hygiene: list[Issue]
    quotes: list[Issue]
    ellipsis: list[Issue]
    scene_breaks: list[Issue]
    paragraphs: ParagraphStats
    paragraph_notes: list[str]
    patterns: list[PatternHit]
    triplets: list[int]
    spacing: list[Issue]
    author_notes: list[Issue] = field(default_factory=list)
    short_sentences: ShortSentenceReport | None = None
    notes: list[str] = field(default_factory=list)
    platform: str = ""

    @property
    def needs_cleanup(self) -> bool:
        return bool(self.hygiene or self.author_notes)

    @property
    def over_patterns(self) -> list[PatternHit]:
        return [p for p in self.patterns if p.over]


def judge_length(length: LengthReport, cfg: ProjectConfig | None) -> str:
    if cfg is None:
        return "프로젝트 설정 없음(기준 미적용)"
    rule = cfg.length
    est = length.muble_estimate
    label = f"{cfg.platform or '플랫폼'} 추정 {est}자"
    if est < rule.platform_min:
        return f"부족: {label} < 최소 {rule.platform_min}자"
    if est < rule.target_min:
        return f"목표 미달: {label} (목표 {rule.target_min}~{rule.target_max})"
    if est > rule.target_max:
        return f"적정(목표 상한 넘음, 참고만): {label} (목표 {rule.target_min}~{rule.target_max})"
    return f"적정: {label} (목표 {rule.target_min}~{rule.target_max})"


def _short_opts(baseline: dict[str, Any]) -> dict[str, Any]:
    """baseline.short_sentences(작품 설정)에서 단문 몰림 기준을 읽는다. 없으면 기본값, limit 없음(기록만)."""
    raw = baseline.get("short_sentences", {})
    keys = ("max_len", "window", "min_short", "limit")
    return {k: raw[k] for k in keys if k in raw}


def check_text(text: str, file_label: str, cfg: ProjectConfig | None) -> EpisodeReport:
    ratio = cfg.length.muble_ratio if cfg else 1.0
    length = count_length(text, ratio)

    patterns_cfg: dict[str, Any] = load_patterns(cfg) if cfg is not None else {}
    notation = cfg.notation if cfg is not None else Notation()

    stats = paragraph_stats(text, notation)
    notes: list[str] = []
    baseline = patterns_cfg.get("baseline", {})
    if baseline:
        warn_avg = baseline.get("narration_avg_len_warn", 40.0)
        warn_multi = baseline.get("multi_sentence_paragraphs_warn", 4)
        base_avg = baseline.get("narration_avg_len", 30.0)
        if stats.narration_avg_len > warn_avg:
            notes.append(
                f"서술 문단 평균 {stats.narration_avg_len}자: 기준선({base_avg}자)보다 김. 한두 문장씩 끊어 빈 줄로 띄우는 작가 문체와 차이."
            )
        if stats.narration_multi_sentence > warn_multi:
            notes.append(f"세 문장 이상 이어진 서술 문단 {stats.narration_multi_sentence}개 (기준 {warn_multi}개 이하).")

    return EpisodeReport(
        file=file_label,
        length=length,
        length_verdict=judge_length(length, cfg),
        hygiene=hygiene_issues(text),
        quotes=quote_issues(text, notation) + quote_style_issues(text, notation),
        ellipsis=ellipsis_issues(text, notation.ellipsis),
        scene_breaks=scene_break_issues(text, notation.scene_break, notation.breath_blank_lines),
        paragraphs=stats,
        paragraph_notes=notes,
        patterns=pattern_hits(text, patterns_cfg.get("patterns", [])),
        triplets=rhetorical_triplets(text, notation),
        spacing=spacing_suspects(text, patterns_cfg.get("spacing_suspects", [])),
        author_notes=author_note_issues(text),
        short_sentences=short_sentence_runs(text, notation, **_short_opts(baseline)),
        platform=cfg.platform if cfg is not None else "",
    )


def check_file(path: Path, cfg: ProjectConfig | None = None) -> EpisodeReport:
    if cfg is None:
        root = find_project_root(path)
        cfg = load_project(root) if root else None
    return check_text(read_text(path), path.name, cfg)


def render(report: EpisodeReport) -> str:
    out: list[str] = [f"# 검수 보고서: {report.file}", ""]
    ln = report.length
    out += [
        "## 분량",
        f"- 공백 제외 {ln.no_space}자 / 공백 포함 {ln.with_space}자 / {report.platform or '플랫폼'} 추정 {ln.muble_estimate}자",
        f"- 판정: {report.length_verdict}",
        "",
        "## 서식 위생 (업로드 전 정리)",
    ]
    out += [i.render() for i in report.hygiene] or ["- 문제 없음"]
    out += ["", "## 작가 메모·괄호 (업로드 전 제거)"]
    out += [i.render() for i in report.author_notes] or ["- 없음"]
    out += ["", "## 따옴표·낫표"]
    out += [i.render() for i in report.quotes] or ["- 문제 없음"]
    out += ["", "## 줄임표 표기"]
    out += [i.render() for i in report.ellipsis] or ["- 통일됨"]
    out += ["", "## 장면 전환 표기"]
    out += [i.render() for i in report.scene_breaks] or ["- 문제 없음"]
    ps = report.paragraphs
    out += [
        "",
        "## 문단 호흡",
        f"- 문단 {ps.paragraphs}개 (서술 {ps.narration}개), 서술 평균 {ps.narration_avg_len}자, "
        f"3문장 이상 서술 문단 {ps.narration_multi_sentence}개, 10자 이하 서술 비율 {ps.narration_short_ratio:.0%}",
    ]
    out += [f"- 주의: {n}" for n in report.paragraph_notes]
    ss = report.short_sentences
    if ss is not None:
        out.append(
            f"- 짧은 단문({ss.max_len}자 이하) {ss.short}/{ss.sentences}문장({ss.ratio:.0%}), "
            f"몰린 구간 {len(ss.runs)}곳" + (f" (허용 {ss.limit})" if ss.limit is not None else "")
        )
        if ss.runs:
            head = "  - **초과** " if ss.over else "  - 참고: "
            out.append(head + "단문이 몰린 구간. 다 고칠 필요는 없고, 강조가 아닌 곳은 문장을 합치거나 길이를 바꿔 볼 것.")
            out += [f"  - {r.start_line}~{r.end_line}행 ({r.short}/{r.sentences}): {r.preview}" for r in ss.runs]
    out += ["", "## AI 습관 패턴"]
    over = report.over_patterns
    if over:
        for p in over:
            shown = ", ".join(str(n) for n in p.lines[:12])
            out.append(f"- **초과** {p.label}: {p.count}회 (허용 {p.limit}) → {shown}행. {p.advice}")
    else:
        out.append("- 허용치 초과 없음")
    info = [p for p in report.patterns if not p.over and p.count > 0]
    if info:
        out.append("- 참고: " + ", ".join(f"{p.label} {p.count}회" for p in info))
    if report.triplets:
        out.append(f"- **셋 나열 의문문**(짧은 의문문 3연속) → {', '.join(map(str, report.triplets))}행")
    out += ["", "## 띄어쓰기 의심 (확인용)"]
    out += [i.render() for i in report.spacing] or ["- 없음"]
    return "\n".join(out)


def report_to_dict(report: EpisodeReport) -> dict[str, Any]:
    d = asdict(report)
    d["needs_cleanup"] = report.needs_cleanup
    return d


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="회차 원고 검수")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    out = setup_output_logging(args.verbose)
    code = 0
    for f in args.files:
        try:
            rep = check_file(f)
        except (OSError, ValueError) as e:
            logger.error("%s 검수 실패: %s", f, e)
            code = 1
            continue
        out.info(json.dumps(report_to_dict(rep), ensure_ascii=False, indent=2) if args.json else render(rep))
        out.info("")
    return code


if __name__ == "__main__":
    sys.exit(main())
