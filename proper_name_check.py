#!/usr/bin/env python3
"""
proper_name_check.py — mechanical proper-name audit (post-translation).

Grep "First de Surname" patterns in English/Spanish output and verify each pair
against source OCR in the same section. Flags CONFLICTS only: when the source text
near "de {surname}" anchors a different first name than the translation rendered
(e.g. xpoual de oli → Gonzalo de Olid).

Does NOT rely on the model knowing it erred.

Usage:
    python proper_name_check.py
    python proper_name_check.py --section 140
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = r"C:\Users\drewc\Downloads\Bernal_Diaz_part_1.txt"
MAP_FILE = os.path.join(PROJECT_DIR, "section_map.json")
OUTPUT_FILE = os.path.join(PROJECT_DIR, "translation_output.txt")
NAME_ISSUES_FILE = os.path.join(PROJECT_DIR, "proper_name_issues.txt")

OUTPUT_SECTION_PARSE_RE = re.compile(
    r"=== (?P<heading>.+?) — Section (?P<n>\d+) ===\s*"
    r"<english>(?P<english>.*?)</english>\s*"
    r"<spanish>(?P<spanish>.*?)</spanish>\s*"
    r"<flags>(?P<flags>.*?)</flags>",
    re.DOTALL | re.IGNORECASE,
)

# Colonial OCR abbreviations → normalized given name
FIRST_NAME_NORM: dict[str, str] = {
    "xpoual": "cristobal", "xpoval": "cristobal", "xpvl": "cristobal",
    "xpo": "cristobal", "xp": "cristobal", "xpual": "cristobal",
    "fran": "francisco", "fran.": "francisco", "fran°": "francisco",
    "hern": "hernando", "hernan": "hernando", "her": "hernando",
    "gon": "gonzalo", "gonz": "gonzalo", "gonç": "gonzalo", "gº": "gonzalo", "g": "gonzalo",
    "ped": "pedro", "pº": "pedro", "p°": "pedro",
    "juan": "juan", "joan": "juan", "jº": "juan",
    "and": "andres", "andr": "andres", "andres": "andres",
    "die": "diego", "fern": "fernando", "mart": "martin",
    "al": "alonso", "alons": "alonso", "anton": "antonio", "ant": "antonio",
    "geronimo": "geronimo", "jeronimo": "geronimo", "ronimo": "geronimo",
    "panfilo": "panfilo", "luys": "luis", "ysabel": "isabel",
    "vasques": "vasquez", "vazquez": "vasquez", "vasquez": "vasquez",
    "dres": "andres", "hulano": "julian", "xpual": "cristobal",
    # accent-stripped output corruption from UTF-8 display
    "pnfilo": "panfilo", "jernimo": "geronimo", "gernimo": "geronimo",
    "cristbal": "cristobal", "andrs": "andres", "antn": "antonio",
    "julin": "julian", "mara": "maria", "daz": "diaz", "nnez": "nunez",
    "lpez": "lopez", "vzquez": "vasquez", "bartolom": "bartolome",
    "huellano": "julian",
    "pon": "ponce", "pone": "ponce", "ponce": "ponce",
    "p": "pedro",  # OCR splits pº into lone p immediately before "de"
    "bartolome": "bartolome", "bartolom": "bartolome",
    "solano": "solano", "solis": "solis",
}

TITLE_TOKENS = frozenset({"fray", "fra", "don", "dona", "doña", "padre", "senor", "señor"})

SKIP_FIRST = frozenset(
    {
        "parte", "partes", "modo", "manera", "tiempo", "año", "anos", "años", "fin",
        "medio", "centro", "nombre", "casa", "lado", "vez", "dia", "día", "punto",
        "camino", "rio", "río", "mar", "tierra", "agua", "noche", "mañana", "tarde",
        "verdad", "servicio", "poder", "reino", "isla", "costa", "punta", "boca",
        "cabo", "sierra", "valle", "monte", "golfo", "bahia", "bahía", "puerto",
        "villa", "ciudad", "pueblo", "capitan", "capitán", "senor", "señor",
        "el", "la", "los", "las", "un", "una", "del", "al", "antes", "que",
        "habamos", "hubiese", "estaba", "fue", "trajo", "cuatro", "real", "cruz",
        "pascua", "audiencia", "medio", "sal", "celo", "cartas", "historias",
        "dignas", "dignos", "relaci", "relacin", "cavados", "mediante", "acuerdo",
    }
)

SKIP_SURNAME = frozenset(
    {
        "que", "ello", "ella", "ellas", "ellos", "tener", "saber", "guerra", "muerte",
        "castilla", "marzo", "arte", "paz", "aquel", "aquella", "aquellos", "obligar",
        "decir", "guardarme", "guardar", "marear", "hechos", "buen", "buena", "cada",
        "cuanto", "antes", "mismo", "modo", "manera", "allí", "alli", "ante",
        "noche", "dia", "día", "año", "anos", "años", "tiempo", "parte", "partes",
        "servicio", "poder", "estos", "estas", "ese", "esa", "demandarle", "quien",
        "santo", "domingo", "navidad", "espiritu", "espritu", "spiritu", "canoas",
        "mora", "luco", "sol", "sols", "burgos", "aylln", "ayllon", "castillo",
    }
)

OUTPUT_DE_NAME_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\.|[°])?)\s+de\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\b"
)

SOURCE_TOKEN_RE = re.compile(
    r"[A-Za-zÁÉÍÓÚÑáéíóúñ][A-Za-zÁÉÍÓÚÑáéíóúñ.\-°ᵒº꠰⁰¹²³]*|p[°º]|pº"
)

KNOWN_GIVEN = frozenset(FIRST_NAME_NORM.values()) | frozenset(
    {
        "pedro", "juan", "gonzalo", "francisco", "hernando", "martin", "alonso",
        "antonio", "diego", "fernando", "cristobal", "andres", "gregorio", "luis",
        "maria", "isabel", "jorge", "bernardo", "rodrigo", "gonzalo", "cortes",
        "velazquez", "narvaez", "panfilo", "geronimo", "julian", "bartolome",
        "vasquez", "ponce", "sandoval",
    }
)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def normalize_first(token: str) -> str:
    t = strip_accents(token.lower().strip(".,;:"))
    t = t.replace("ç", "c")
    if t in FIRST_NAME_NORM:
        return FIRST_NAME_NORM[t]
    t = re.sub(r"[^a-z]", "", t)
    if t in FIRST_NAME_NORM:
        return FIRST_NAME_NORM[t]
    return t


def normalize_surname(token: str) -> str:
    t = strip_accents(token.lower().strip(".,;:"))
    t = t.replace("ç", "c")
    return re.sub(r"[^a-z]", "", t)


def is_plausible_name(token: str) -> bool:
    raw = token.lower().strip(".,:")
    n = normalize_first(token)
    if not n or n in SKIP_FIRST:
        return False
    if raw in TITLE_TOKENS:
        return False
    if n in FIRST_NAME_NORM.values() or raw in FIRST_NAME_NORM:
        return len(n) >= 3 or raw in FIRST_NAME_NORM
    if len(n) < 3:
        return False
    # reject obvious OCR junk / common Spanish
    if n in {"de", "se", "en", "el", "la", "lo", "le", "mo", "co", "vn", "vno", "con", "dro", "easen"}:
        return False
    if len(n) == 3 and n not in FIRST_NAME_NORM.values():
        return False
    return bool(re.fullmatch(r"[a-z]{3,12}", n))


def fuzzy_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if a[:4] == b[:4] and len(a) >= 4 and len(b) >= 4:
        return True
    if len(a) >= 4 and len(b) >= 4:
        if SequenceMatcher(None, a, b).ratio() >= 0.82:
            return True
    return False


def first_names_compatible(output_first: str, source_first: str) -> bool:
    o = normalize_first(output_first)
    s = normalize_first(source_first)
    if not o or not s:
        return True
    return fuzzy_match(o, s)


def extract_output_pairs(text: str) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for m in OUTPUT_DE_NAME_RE.finditer(text):
        first_raw, sur_raw = m.group(1), m.group(2)
        first = normalize_first(first_raw)
        sur = normalize_surname(sur_raw)
        if not first or not sur or len(first) < 3 or len(sur) < 4:
            continue
        if first in SKIP_FIRST or sur in SKIP_SURNAME:
            continue
        if sur in ("mexico", "cuba", "espana", "indias", "florida", "panama"):
            continue
        pairs.add((first, sur))
    return pairs


def source_first_names_for_surname(source: str, surname: str) -> set[str]:
    """First names immediately before each 'de {surname}' anchor (within ~22 chars)."""
    sur = normalize_surname(surname)
    if not sur:
        return set()
    found: set[str] = set()
    pattern = re.compile(
        rf"\bde\s+({re.escape(sur[:4])}\w{{0,10}})\b", re.IGNORECASE
    )
    for m in pattern.finditer(source):
        window = source[max(0, m.start() - 22) : m.start()]
        tokens = SOURCE_TOKEN_RE.findall(window)
        # Walk backward skipping titles to find given name
        candidates = tokens[-4:]
        # Prefer token immediately before "de" (handles pº → p, xpoual, etc.)
        if candidates:
            imm = candidates[-1]
            imm_n = normalize_first(imm)
            if imm_n in KNOWN_GIVEN or imm.lower().strip(".,:") in FIRST_NAME_NORM:
                found.add(imm_n)
                continue
        for i in range(len(candidates) - 2, -1, -1):
            tok = candidates[i]
            raw = tok.lower().strip(".,:")
            if raw in TITLE_TOKENS:
                continue
            if is_plausible_name(tok):
                found.add(normalize_first(tok))
                break
    return found


def first_appears_in_source(first: str, source: str) -> bool:
    """True if normalized first (or OCR alias) appears anywhere in source section."""
    target = normalize_first(first)
    if not target:
        return False
    for tok in SOURCE_TOKEN_RE.findall(source):
        if first_names_compatible(target, tok):
            return True
    # Lone p before "de" = Pedro in this corpus
    if target == "pedro" and re.search(r"\bp\s+de\s+", source, re.IGNORECASE):
        return True
    return False


def check_pair_in_source(first: str, surname: str, source: str) -> tuple[bool, str]:
    """
    Return (ok, reason). Only fails on CONFLICT: source anchors a different person.
    """
    source_firsts = source_first_names_for_surname(source, surname)
    plausible = {sf for sf in source_firsts if sf in KNOWN_GIVEN}

    if not plausible:
        # No anchor — cannot verify mechanically; do not flag
        return True, "no source anchor"

    if any(first_names_compatible(first, sf) for sf in plausible):
        return True, "matches source anchor"

    # Output first appears elsewhere in section (may be valid, anchor is elsewhere)
    if first_appears_in_source(first, source):
        return True, "first name found elsewhere in source"

    return False, (
        f"CONFLICT: output '{first} de {surname}' — source near 'de {surname}' "
        f"has: {', '.join(sorted(plausible))}"
    )


def parse_output_sections(output_path: str) -> dict[int, dict[str, str]]:
    text = read_text(output_path)
    result: dict[int, dict[str, str]] = {}
    for m in OUTPUT_SECTION_PARSE_RE.finditer(text):
        n = int(m.group("n"))
        result[n] = {
            "heading": m.group("heading").strip(),
            "english": m.group("english").strip(),
            "spanish": m.group("spanish").strip(),
        }
    return result


def run_proper_name_check(
    source_path: str,
    map_path: str,
    output_path: str,
    issues_path: str,
    section_filter: set[int] | None = None,
) -> int:
    if not os.path.isfile(output_path):
        print(f"ERROR: output not found: {output_path}", file=sys.stderr)
        return 1
    if not os.path.isfile(map_path):
        print(f"ERROR: map not found: {map_path}", file=sys.stderr)
        return 1
    if not os.path.isfile(source_path):
        print(f"ERROR: source not found: {source_path}", file=sys.stderr)
        return 1

    source = read_text(source_path)
    map_data = json.load(open(map_path, encoding="utf-8"))
    sections_by_n = {s["n"]: s for s in map_data.get("sections", [])}
    parsed = parse_output_sections(output_path)

    issues: list[str] = []
    flagged_sections: list[int] = []

    print(f"Proper-name cross-check: {len(parsed)} sections\n")

    for n in sorted(parsed):
        if section_filter and n not in section_filter:
            continue
        sec = parsed[n]
        map_sec = sections_by_n.get(n)
        if not map_sec:
            continue
        chunk = source[map_sec["start_offset"] : map_sec["end_offset"]]
        combined = sec["english"] + "\n" + sec["spanish"]

        out_pairs = extract_output_pairs(combined)
        if not out_pairs:
            print(f"  Section {n}: OK (no person 'de' pairs)")
            continue

        section_problems: list[str] = []
        for first, sur in sorted(out_pairs):
            ok, reason = check_pair_in_source(first, sur, chunk)
            if not ok:
                section_problems.append(f"    PROPER NAME: {first} de {sur} — {reason}")

        if section_problems:
            flagged_sections.append(n)
            issues.append(f"Section {n} — {sec['heading'][:70]}")
            issues.extend(section_problems)
            issues.append("")
            print(f"  Section {n} FAIL ({len(section_problems)} conflict(s))")
            for line in section_problems:
                print(line)
        else:
            print(f"  Section {n}: OK ({len(out_pairs)} pair(s) checked)")

    with open(issues_path, "w", encoding="utf-8") as f:
        if issues:
            f.write("PROPER NAME CROSS-CHECK ISSUES\n\n")
            f.write("\n".join(issues))
        else:
            f.write("")

    print(f"\n--- {len(flagged_sections)} section(s) with name conflicts ---")
    if flagged_sections:
        print(f"Details: {issues_path}")
    else:
        print("No conflicts detected.")
    return 1 if flagged_sections else 0


def main() -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass

    parser = argparse.ArgumentParser(description="Mechanical proper-name cross-check.")
    parser.add_argument("--section", type=int, action="append", dest="sections")
    parser.add_argument("--source", default=SOURCE_FILE)
    parser.add_argument("--map", default=MAP_FILE)
    parser.add_argument("--output", default=OUTPUT_FILE)
    parser.add_argument("--issues", default=NAME_ISSUES_FILE)
    args = parser.parse_args()

    filt = set(args.sections) if args.sections else None
    return run_proper_name_check(
        args.source, args.map, args.output, args.issues, filt
    )


if __name__ == "__main__":
    sys.exit(main())
