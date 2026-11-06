#!/usr/bin/env python3
"""Codebook and coded-segment validation with transparent descriptive outputs.

Requires only Python's standard library. Input contains structured annotations,
not raw transcripts. Example input distributed with this project is synthetic.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import itertools
import json
import re
from collections import defaultdict
from pathlib import Path

CODEBOOK_COLUMNS = ("code_id", "theme", "definition")
ANNOTATION_COLUMNS = ("interview_id", "segment_id", "platform", "code_id")
TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}$")
PLATFORMS = {"WeChat", "Weibo", "Twitter", "Multiple", "Unspecified"}


class DataValidationError(ValueError):
    """Input does not satisfy this project's explicit schema."""


def read_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or tuple(reader.fieldnames) != fields:
            raise DataValidationError(
                f"{path.name}: expected exactly these fields: {', '.join(fields)}"
            )
        result = []
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise DataValidationError(f"{path.name}:{line}: malformed row")
            cleaned = {key: value.strip() for key, value in row.items()}
            if any(not value for value in cleaned.values()):
                raise DataValidationError(f"{path.name}:{line}: missing required value")
            result.append(cleaned)
    if not result:
        raise DataValidationError(f"{path.name}: empty table")
    return result


def analyze(codebook_path: Path, coding_path: Path, *, label: str = "Synthetic example") -> dict:
    """Count distinct interviews and segments, not arbitrary annotation rows."""
    if not label.strip() or len(label) > 100 or '\n' in label or '\r' in label:
        raise DataValidationError("Dataset label must be one nonempty line, at most 100 characters")
    codebook = read_csv(codebook_path, CODEBOOK_COLUMNS)
    definitions = {}
    for item in codebook:
        code = item["code_id"]
        if not TOKEN.fullmatch(code) or code in definitions:
            raise DataValidationError(f"Duplicate or invalid code_id {code!r}")
        definitions[code] = item
    rows = read_csv(coding_path, ANNOTATION_COLUMNS)
    seen_assignments: set[tuple[str, str, str]] = set()
    segment_platform: dict[tuple[str, str], str] = {}
    segment_themes: dict[tuple[str, str], set[str]] = defaultdict(set)
    theme_interviews: dict[str, set[str]] = defaultdict(set)
    theme_segments: dict[str, set[tuple[str, str]]] = defaultdict(set)
    code_segments: dict[str, set[tuple[str, str]]] = defaultdict(set)
    platform_segments: dict[str, set[tuple[str, str]]] = defaultdict(set)
    interview_ids: set[str] = set()
    for line, row in enumerate(rows, 2):
        interview, segment, platform, code = [row[column] for column in ANNOTATION_COLUMNS]
        if not TOKEN.fullmatch(interview) or not TOKEN.fullmatch(segment):
            raise DataValidationError(f"{coding_path.name}:{line}: use pseudonymous ID tokens")
        if platform not in PLATFORMS:
            raise DataValidationError(f"{coding_path.name}:{line}: unexpected platform tag {platform!r}")
        if code not in definitions:
            raise DataValidationError(f"{coding_path.name}:{line}: unknown code {code!r}")
        assignment = (interview, segment, code)
        if assignment in seen_assignments:
            raise DataValidationError(f"{coding_path.name}:{line}: duplicate assignment {assignment}")
        seen_assignments.add(assignment)
        segment_key = (interview, segment)
        if segment_key in segment_platform and segment_platform[segment_key] != platform:
            raise DataValidationError(
                f"{coding_path.name}:{line}: conflicting platform tags for {segment_key}"
            )
        segment_platform[segment_key] = platform
        theme = definitions[code]["theme"]
        segment_themes[segment_key].add(theme)
        theme_interviews[theme].add(interview)
        theme_segments[theme].add(segment_key)
        code_segments[code].add(segment_key)
        platform_segments[platform].add(segment_key)
        interview_ids.add(interview)

    themes = sorted({row["theme"] for row in codebook})
    platform_order = sorted(platform_segments)
    intersections: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for segment, assigned in segment_themes.items():
        for a, b in itertools.combinations(sorted(assigned), 2):
            intersections[(a, b)].add(segment)

    report = {
        "dataset_label": label.strip(),
        "inputs": {
            "codebook_sha256": hashlib.sha256(codebook_path.read_bytes()).hexdigest(),
            "coded_segments_sha256": hashlib.sha256(coding_path.read_bytes()).hexdigest(),
        },
        "denominators": {
            "distinct_interviews": len(interview_ids),
            "distinct_segments": len(segment_platform),
            "code_assignments": len(rows),
            "codebook_codes": len(definitions),
        },
        "themes": [
            {"theme": theme, "distinct_interviews": len(theme_interviews[theme]),
             "distinct_segments": len(theme_segments[theme])} for theme in themes
        ],
        "codes": [
            {"code_id": code, "theme": definitions[code]["theme"],
             "distinct_segments": len(code_segments[code])} for code in sorted(definitions)
        ],
        "platform_tags": [
            {"platform": platform, "distinct_segments": len(platform_segments[platform])}
            for platform in platform_order
        ],
        "platform_by_theme": [
            {"platform": platform, "theme": theme, "distinct_segments": len(
                platform_segments[platform].intersection(theme_segments[theme]))}
            for platform in platform_order for theme in themes
        ],
        "theme_cooccurrence": [
            {"theme_a": a, "theme_b": b, "distinct_segments": len(intersections[(a, b)])}
            for a, b in itertools.combinations(themes, 2)
        ],
        "interpretation_notes": [
            "The interview, segment, and assignment denominators are different units.",
            "A segment may have several codes or themes; theme totals are not additive.",
            "The platform field tags coded segments; it is not a measure of platform usage.",
            "Co-occurrence means two themes were assigned to the same coded segment, not statistical association.",
            "Descriptive tables are not causal estimates, population prevalence, or intercoder agreement.",
        ],
    }
    return report


def markdown(report: dict) -> str:
    d = report["denominators"]
    heading = report["dataset_label"].replace("|", "\\|")
    lines = ["# Qualitative coding: validation and descriptive summary", "",
             f"**Dataset:** {heading}", "",
             f"**Units:** {d['distinct_interviews']} interview IDs · {d['distinct_segments']} distinct segments · "
             f"{d['code_assignments']} assignments · {d['codebook_codes']} codes.", "",
             "## Theme coverage", "", "| Theme | Interview IDs | Segments |", "|---|---:|---:|"]
    for item in report["themes"]:
        safe = item["theme"].replace("|", "\\|")
        lines.append(f"| {safe} | {item['distinct_interviews']} | {item['distinct_segments']} |")
    lines += ["", "## Platform × theme (coded-segment counts)", "", "| Platform tag | Theme | Segments |", "|---|---|---:|"]
    for item in report["platform_by_theme"]:
        safe_theme = item["theme"].replace("|", "\\|")
        lines.append(f"| {item['platform']} | {safe_theme} | {item['distinct_segments']} |")
    lines += ["", "## Interpretation", ""]
    lines += [f"- {line}" for line in report["interpretation_notes"]]
    lines += ["", "## SHA-256 inputs", "",
              f"- Codebook: `{report['inputs']['codebook_sha256']}`",
              f"- Coding matrix: `{report['inputs']['coded_segments_sha256']}`", ""]
    return "\n".join(lines)


def svg_chart(report: dict) -> str:
    """Local vector chart, no dependencies or external fonts. Safe escaped labels."""
    records = report["themes"]
    maximum = max(1, *(item["distinct_segments"] for item in records))
    width = 950
    height = 122 + 62 * len(records)
    title = html.escape(report["dataset_label"], quote=True)
    chunks = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Theme coverage chart: {title}">',
              '<rect width="100%" height="100%" fill="#f8fafc"/>',
              f'<text x="28" y="32" fill="#17253b" font-size="19" font-family="sans-serif" font-weight="bold">{title} · theme coverage</text>',
              '<text x="28" y="55" fill="#4b5563" font-size="13" font-family="sans-serif">Distinct coded segments; themes may overlap</text>']
    for index, item in enumerate(records):
        y = 91 + index * 62
        label = html.escape(item["theme"], quote=True)
        count = item["distinct_segments"]
        bar_width = round(342 * count / maximum)
        chunks.extend([
            f'<text x="28" y="{y}" fill="#243046" font-size="13" font-family="sans-serif">{label}</text>',
            f'<rect x="525" y="{y-16}" width="342" height="18" rx="5" fill="#dae4eb"/>',
            f'<rect x="525" y="{y-16}" width="{bar_width}" height="18" rx="5" fill="#276e84"/>',
            f'<text x="881" y="{y}" fill="#243046" font-size="14" font-family="sans-serif">{count}</text>'
        ])
    chunks.append('</svg>')
    return '\n'.join(chunks) + '\n'


def write_table(path: Path, columns: tuple[str, ...], rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(report: dict, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(markdown(report), encoding="utf-8")
    (output / "theme_coverage.svg").write_text(svg_chart(report), encoding="utf-8")
    for filename, columns, key in [
        ("themes.csv", ("theme", "distinct_interviews", "distinct_segments"), "themes"),
        ("codes.csv", ("code_id", "theme", "distinct_segments"), "codes"),
        ("platform_theme.csv", ("platform", "theme", "distinct_segments"), "platform_by_theme"),
        ("cooccurrence.csv", ("theme_a", "theme_b", "distinct_segments"), "theme_cooccurrence"),
    ]:
        write_table(output / filename, columns, report[key])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate qualitative coding exports and generate descriptive tables")
    parser.add_argument("--codebook", type=Path, required=True)
    parser.add_argument("--coding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="Synthetic example", help="Dataset label displayed in every output")
    args = parser.parse_args(argv)
    try:
        report = analyze(args.codebook, args.coding, label=args.label)
        write_outputs(report, args.output)
    except (OSError, UnicodeError, DataValidationError) as exc:
        parser.error(str(exc))
    print("Validated: " + ", ".join(f"{k}={v}" for k, v in report["denominators"].items()))
    print("Outputs: " + str(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
