# Bernal Díaz — Tomo I Translation Pipeline

Batch literary translation of *Historia verdadera de la conquista de la Nueva España* (García 1904 OCR) into paired modern **English + Spanish**, using the Wikowí Universal Translation Protocol (UTP).

Repository: https://github.com/angryhephilump-tech/Translator-final

Each chapter is translated in a **fresh** `cursor-agent` process — no context bleed between sections.

## Pipeline checklist (what the runner implements)

| # | Feature | Status |
|---|---------|--------|
| 1 | Fresh context per section (one `cursor-agent` call, new process) | ✅ |
| 2 | Frozen section map (`--build-map`, anchors, source SHA256) | ✅ |
| 3 | Map document only, not apparatus (regex + AI prompt rules) | ✅ |
| 4 | Cross-check map count (regex vs AI → `map_problems.txt`) | ✅ |
| 5 | Ratio gate (en/es &lt; 0.7 → `low_ratio_sections.txt` + hard fail) | ✅ |
| 6 | Catch-and-mark blocks (`skipped_sections.txt`, run continues) | ✅ |
| 7 | Resume + source-hash guard | ✅ |
| 8 | Voice carry + `voice_log.txt` | ✅ |
| 9 | Model pinned: **Composer 2.5** (`MODEL = composer-2.5`) | ✅ |
| 10 | Proper names itemized in flags (`PROPER NAME:` lines in UTP) | ✅ |
| 11 | Honest flag labeling (representative sample, no no-op edits) | ✅ |
| 12 | **Mechanical proper-name cross-check** (`proper_name_check.py`) | ✅ |

## Setup

1. Install [Cursor CLI](https://cursor.com/docs/cli/overview):  
   `irm 'https://cursor.com/install?win32=true' | iex`
2. Authenticate: `cursor-agent login`
3. Place the OCR source at `C:\Users\drewc\Downloads\Bernal_Diaz_part_1.txt` (or edit `SOURCE_FILE` in `translate_runner.py`).
4. Python 3.10+

## Commands

```powershell
cd C:\Users\drewc\Projects\translation

# One-time: freeze section boundaries (140 chapters, regex headers)
python translate_runner.py --build-map

# Full run or resume (skips sections already in output)
python translate_runner.py

# Audit output (truncation, ratio, apparatus — no AI)
python translate_runner.py --validate-output

# Mechanical proper-name net (Gonzalo/Cristóbal class — does not trust flags)
python translate_runner.py --check-proper-names
# or: python proper_name_check.py

# Audit + apply confirmed corrections only (edit CORRECTIONS in audit_fix.py first)
python audit_fix.py
# → audit_report.txt, translation_output_clean.txt

# Re-translate failed sections (see rerun_sections.txt after a run)
python translate_runner.py --sections 30,73 --force

# Live progress dashboard (separate terminal)
python progress_server.py
# → http://127.0.0.1:8765/
```

## Files

| File | Purpose |
|------|---------|
| `translate_runner.py` | Orchestrator: map, translate, QA gates, retries |
| `proper_name_check.py` | Post-run mechanical name cross-check |
| `audit_fix.py` | Audit report + apply confirmed CORRECTIONS only |
| `utp.txt` | Wikowí headless translation protocol |
| `section_map.json` | Frozen byte-offset map (140 sections) |
| `translation_output.txt` | Deliverable: en/es/flags per section |
| `voice_log.txt` | Detected voice label per section |
| `rerun_sections.txt` | Section numbers to re-run after failures |
| `proper_name_issues.txt` | Output of `--check-proper-names` |
| `audit_report.txt` | Output of `audit_fix.py` |
| `translation_output_clean.txt` | Corrected copy from `audit_fix.py` |
| `progress_server.py` | Browser dashboard |

## QA layers

1. **In-run gates** (hard-fail + retry): truncation, en/es parity, source coverage, apparatus strip, Olid heuristic, false flag claims.
2. **`--validate-output`**: audit full output without calling the model.
3. **`--check-proper-names`**: grep `First de Surname` pairs in output vs source tokens nearby — catches name swaps the flag layer missed.

## Source

Public-domain OCR: Bernal Díaz del Castillo, ed. García (1904), Tomo I. Not included in this repo (large file; path configured in runner).
