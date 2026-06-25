#!/usr/bin/env python3
"""
audit_fix.py — mechanical audit of a sectioned translation file.

This script READS your translation, RUNS checks, WRITES a report, and applies
ONLY replacements you have listed in CORRECTIONS below. It never guesses.

To fix a name or phrase after reviewing the report:
  1. Open CORRECTIONS at the top of this file.
  2. Add a line like:  "Wrong text": "Right text",
  3. Run:  python audit_fix.py

Pure standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# CONFIG — edit these paths and CORRECTIONS, then rerun
# ---------------------------------------------------------------------------

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

OUTPUT_FILE = os.path.join(PROJECT_DIR, "translation_output.txt")
SOURCE_FILE = r"C:\Users\drewc\Downloads\Bernal_Diaz_part_1.txt"  # optional; set "" to skip check 6
REPORT_FILE = os.path.join(PROJECT_DIR, "audit_report.txt")
CLEAN_FILE = os.path.join(PROJECT_DIR, "translation_output_clean.txt")

RATIO_THRESHOLD = 0.7

# CONFIRMED replacements only. Nothing outside this dict is ever auto-changed.
# Add entries after you review the audit report. Example:
CORRECTIONS: dict[str, str] = {
    # "Gonzalo de Olid": "Cristóbal de Olid",
    # "Gerónimo de Aguilar": "Jerónimo de Aguilar",
    # "Antonio de Alaminos": "Antón de Alaminos",
    # "Panfilo de Narváez": "Pánfilo de Narváez",
}

# ---------------------------------------------------------------------------
# Constants (usually no need to edit)
# ---------------------------------------------------------------------------

SECTION_HEADER_RE = re.compile(
    r"=== (?P<heading>.+?) — Section (?P<n>\d+) ===\s*"
    r"<english>(?P<english>.*?)</english>\s*"
    r"<spanish>(?P<spanish>.*?)</spanish>\s*"
    r"<flags>(?P<flags>.*?)</flags>",
    re.DOTALL | re.IGNORECASE,
)

LACUNA_EN = "[words missing]"
LACUNA_ES = "[palabras faltantes]"
MIN_WORDS_SHORT = 20
MIN_WORDS_LONG = 80  # "long" = other block has at least this many words

# "Pedro de Alvarado" style
DE_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\.|[°])?)\s+de\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\b"
)

# "Hernando Cortés" style (two capitalized tokens, no "de")
PLAIN_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\b"
)

# Skip common non-person pairs for plain-name scan
SKIP_PLAIN_FIRST = frozenset(
    {
        "New", "Royal", "Saint", "Santa", "San", "Don", "Doña", "Chapter",
        "Capitulo", "Great", "Very", "His", "Her", "The", "And", "But", "For",
        "When", "Then", "After", "Before", "Let", "May", "God", "Lord",
        "South", "North", "East", "West", "Cape", "Isla", "Real", "Rich",
    }
)

FLAG_ARROW_RE = re.compile(
    r"([^\s→\-]+(?:\s+[^\s→\-]+)*)\s*(?:→|->)\s*(\S+)"
)

# ---------------------------------------------------------------------------


def read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def word_count(text: str) -> int:
    return len(text.split()) if text.strip() else 0


def parse_sections(text: str) -> list[dict]:
    """Split OUTPUT_FILE into sections with heading, n, english, spanish, flags."""
    sections: list[dict] = []
    for m in SECTION_HEADER_RE.finditer(text):
        sections.append(
            {
                "heading": m.group("heading").strip(),
                "n": int(m.group("n")),
                "english": m.group("english").strip(),
                "spanish": m.group("spanish").strip(),
                "flags": m.group("flags").strip(),
            }
        )
    return sections


def check_compression(sections: list[dict]) -> list[str]:
    lines: list[str] = []
    for sec in sections:
        en_w = word_count(sec["english"])
        es_w = word_count(sec["spanish"])
        if es_w == 0:
            continue
        ratio = en_w / es_w
        if ratio < RATIO_THRESHOLD:
            lines.append(
                f"  Section {sec['n']} — {sec['heading'][:60]}\n"
                f"    COMPRESSED — re-translate (en/es = {ratio:.2f}, "
                f"{en_w} en / {es_w} es words, threshold {RATIO_THRESHOLD})"
            )
    return lines


def collect_de_name_firsts(english_all: str) -> set[str]:
    """Given names seen in 'First de Surname' patterns."""
    return {first.lower() for first, _ in DE_NAME_RE.findall(english_all)}


def collect_name_counts(english_all: str) -> dict[str, dict[str, int]]:
    """surname -> {firstname: count} from English text."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    known_firsts = collect_de_name_firsts(english_all)

    for first, sur in DE_NAME_RE.findall(english_all):
        if len(sur) >= 4:
            counts[sur.lower()][first.lower()] += 1

    for first, sur in PLAIN_NAME_RE.findall(english_all):
        if first in SKIP_PLAIN_FIRST:
            continue
        # Only count plain pairs when first name also appears in "X de Y" form
        if first.lower() not in known_firsts:
            continue
        if len(sur) >= 4:
            counts[sur.lower()][first.lower()] += 1

    return counts


def check_name_drift(sections: list[dict]) -> tuple[list[str], set[str]]:
    """Return report lines and set of flagged full names for source grep."""
    english_all = "\n".join(s["english"] for s in sections)
    counts = collect_name_counts(english_all)
    lines: list[str] = []
    flagged_names: set[str] = set()

    for sur, first_counts in sorted(counts.items()):
        if len(first_counts) <= 1:
            continue
        total = sum(first_counts.values())
        minority = [
            (first, cnt)
            for first, cnt in first_counts.items()
            if cnt / total < 0.40
        ]
        if not minority:
            continue
        lines.append(
            f"  REVIEW — possible name bleed (may be a place/river/real "
            f"namesake — human decides)\n"
            f"    Surname '{sur.title()}': "
            + ", ".join(f"{k.title()}={v}" for k, v in sorted(first_counts.items(), key=lambda x: -x[1]))
            + f"  (total {total})"
        )
        for first, _ in minority:
            flagged_names.add(f"{first.title()} de {sur.title()}")
        for first in first_counts:
            flagged_names.add(f"{first.title()} de {sur.title()}")

    if not lines:
        lines.append("  (none)")
    return lines, flagged_names


def check_flag_laundering(sections: list[dict]) -> tuple[list[str], set[str]]:
    lines: list[str] = []
    flagged: set[str] = set()

    for sec in sections:
        for m in FLAG_ARROW_RE.finditer(sec["flags"]):
            src, dst = m.group(1).strip(), m.group(2).strip(".,;:")
            # Proper name if destination starts with uppercase letter
            if dst and dst[0].isupper():
                lines.append(
                    f"  Section {sec['n']} — {sec['heading'][:50]}\n"
                    f"    PROPER-NAME CHANGE IN FLAGS — verify against source: "
                    f"{src} → {dst}"
                )
                flagged.add(dst)

    if not lines:
        lines.append("  (none)")
    return lines, flagged


def check_lacuna_match(sections: list[dict]) -> list[str]:
    lines: list[str] = []
    for sec in sections:
        en_n = sec["english"].count(LACUNA_EN)
        es_n = sec["spanish"].count(LACUNA_ES)
        if en_n != es_n:
            lines.append(
                f"  Section {sec['n']} — {sec['heading'][:60]}\n"
                f"    LACUNA MISMATCH — one language may have healed a gap "
                f"({LACUNA_EN}: {en_n}, {LACUNA_ES}: {es_n})"
            )
    if not lines:
        lines.append("  (none)")
    return lines


def check_completeness(sections: list[dict]) -> list[str]:
    lines: list[str] = []
    numbers = sorted(s["n"] for s in sections)

    for sec in sections:
        en_w = word_count(sec["english"])
        es_w = word_count(sec["spanish"])
        if en_w == 0 and es_w > 0:
            lines.append(
                f"  Section {sec['n']} — {sec['heading'][:60]}\n"
                f"    COMPLETENESS — English block empty ({es_w} Spanish words)"
            )
        elif es_w == 0 and en_w > 0:
            lines.append(
                f"  Section {sec['n']} — {sec['heading'][:60]}\n"
                f"    COMPLETENESS — Spanish block empty ({en_w} English words)"
            )
        elif en_w < MIN_WORDS_SHORT and es_w >= MIN_WORDS_LONG:
            lines.append(
                f"  Section {sec['n']} — {sec['heading'][:60]}\n"
                f"    COMPLETENESS — English very short ({en_w} words) vs "
                f"Spanish long ({es_w} words)"
            )
        elif es_w < MIN_WORDS_SHORT and en_w >= MIN_WORDS_LONG:
            lines.append(
                f"  Section {sec['n']} — {sec['heading'][:60]}\n"
                f"    COMPLETENESS — Spanish very short ({es_w} words) vs "
                f"English long ({en_w} words)"
            )

    if numbers:
        expected = set(range(numbers[0], numbers[-1] + 1))
        missing = sorted(expected - set(numbers))
        if missing:
            lines.append(
                f"  COMPLETENESS — missing section numbers: "
                + ", ".join(str(n) for n in missing)
            )

    if not lines:
        lines.append("  (none)")
    return lines


def archaic_grep_forms(name: str) -> list[str]:
    """A few likely source forms to search — hints only, not verdicts."""
    forms = [name]
    lower = name.lower()
    forms.append(lower)
    # strip accents roughly for OCR grep
    stripped = (
        lower.replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )
    if stripped != lower:
        forms.append(stripped)
    # first token abbreviations common in this corpus
    parts = name.split()
    if parts:
        forms.append(parts[0][:4].lower())
        if len(parts) >= 3 and parts[1].lower() == "de":
            forms.append(f"{parts[0][:3].lower()} de {parts[2][:3].lower()}")
    return list(dict.fromkeys(forms))  # dedupe, preserve order


def check_source_grep_hints(
    source_text: str, flagged_names: set[str]
) -> list[str]:
    lines: list[str] = []
    if not source_text or not flagged_names:
        return ["  (skipped — no SOURCE_FILE or no flagged names)"]

    src_lower = source_text.lower()
    for name in sorted(flagged_names):
        hits: list[str] = []
        for form in archaic_grep_forms(name):
            if form.lower() in src_lower:
                hits.append(form)
        if hits:
            lines.append(f"  {name}: FOUND in source as {', '.join(repr(h) for h in hits)}")
        else:
            lines.append(f"  {name}: NOT FOUND in source (any tried form) — review carefully")
    return lines


def apply_corrections(source_text: str) -> tuple[str, list[str], list[str]]:
    """Copy text, apply CORRECTIONS dict only. Returns (clean_text, log_lines, warnings)."""
    clean = source_text
    log: list[str] = []
    warnings: list[str] = []

    if not CORRECTIONS:
        log.append("  (no entries in CORRECTIONS — clean file is an unchanged copy)")
        return clean, log, warnings

    for old, new in CORRECTIONS.items():
        count = clean.count(old)
        if count == 0:
            warnings.append(f"  WARNING: CORRECTIONS key matched 0 times: {old!r}")
        else:
            clean = clean.replace(old, new)
            log.append(f"  {old} -> {new}: {count} replacement(s)")
    return clean, log, warnings


def run_audit(
    output_path: str,
    source_path: str | None,
    report_path: str,
    clean_path: str,
) -> int:
    if not os.path.isfile(output_path):
        print(f"ERROR: output not found: {output_path}", file=sys.stderr)
        return 1

    raw = read_text(output_path)
    sections = parse_sections(raw)
    if not sections:
        print(f"ERROR: no sections parsed from {output_path}", file=sys.stderr)
        return 1

    source_text = read_text(source_path) if source_path and os.path.isfile(source_path) else ""

    compression = check_compression(sections)
    name_drift, drift_names = check_name_drift(sections)
    laundering, launder_names = check_flag_laundering(sections)
    lacuna = check_lacuna_match(sections)
    completeness = check_completeness(sections)

    grep_names = drift_names | launder_names
    grep_hints = check_source_grep_hints(source_text, grep_names)

    clean_text, corr_log, corr_warnings = apply_corrections(raw)

    report_parts = [
        "AUDIT REPORT",
        f"File: {output_path}",
        f"Sections parsed: {len(sections)}",
        "",
        "=" * 60,
        "1. COMPRESSION (en/es ratio < {:.1f})".format(RATIO_THRESHOLD),
        "=" * 60,
        *(compression if compression else ["  (none)"]),
        "",
        "=" * 60,
        "2. NAME DRIFT (English — possible bleed across sections)",
        "=" * 60,
        *name_drift,
        "",
        "=" * 60,
        "3. FLAG-LAUNDERING (proper-name changes disguised in flags)",
        "=" * 60,
        *laundering,
        "",
        "=" * 60,
        "4. LACUNA MATCH ([words missing] vs [palabras faltantes])",
        "=" * 60,
        *lacuna,
        "",
        "=" * 60,
        "5. COMPLETENESS (empty/short blocks, missing section numbers)",
        "=" * 60,
        *completeness,
        "",
        "=" * 60,
        "6. SOURCE GREP-HINTS (for names flagged in checks 2 & 3)",
        "=" * 60,
        *grep_hints,
        "",
        "=" * 60,
        "CORRECTIONS APPLIED (CONFIRMED LIST ONLY)",
        "=" * 60,
        *corr_log,
        *corr_warnings,
    ]
    report = "\n".join(report_parts) + "\n"
    write_text(report_path, report)
    write_text(clean_path, clean_text)

    n_compression = len(compression)
    n_drift = sum(1 for line in name_drift if line.startswith("  REVIEW"))
    n_launder = sum(1 for line in laundering if "PROPER-NAME CHANGE" in line)
    n_lacuna = sum(1 for line in lacuna if "LACUNA MISMATCH" in line)
    n_complete = sum(
        1 for line in completeness if line.startswith("  Section") or line.startswith("  COMPLETENESS")
    )
    n_corr = sum(
        1 for line in corr_log if "replacement" in line
    )

    print(f"Audited {len(sections)} sections from {output_path}")
    print(f"Report written: {report_path}")
    print(f"Clean copy written: {clean_path}")
    print()
    print("Summary:")
    print(f"  Compression flags:     {n_compression}")
    print(f"  Name-drift flags:      {n_drift}")
    print(f"  Flag-laundering flags: {n_launder}")
    print(f"  Lacuna mismatch flags: {n_lacuna}")
    print(f"  Completeness flags:    {n_complete}")
    print(f"  Corrections applied:   {n_corr} type(s)")
    if corr_warnings:
        print(f"  Correction warnings:   {len(corr_warnings)} (see report)")

    return 0


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass

    parser = argparse.ArgumentParser(
        description="Audit a sectioned translation; apply only CORRECTIONS from this file."
    )
    parser.add_argument("--output", default=OUTPUT_FILE, help="Translation file to audit")
    parser.add_argument("--source", default=SOURCE_FILE or None, help="Raw OCR source (optional)")
    parser.add_argument("--report", default=REPORT_FILE, help="Where to write the report")
    parser.add_argument("--clean", default=CLEAN_FILE, help="Where to write corrected copy")
    args = parser.parse_args()

    source = args.source if args.source else None
    return run_audit(args.output, source, args.report, args.clean)


if __name__ == "__main__":
    sys.exit(main())
