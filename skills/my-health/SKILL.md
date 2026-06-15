---
name: my-health
description: "Answer questions about Karen Pullen's real health data from MD Anderson MyChart via Epic FHIR. Fully set up and working — no setup needed."
version: 2.1.0
author: drewp
metadata:
  hermes:
    tags: [health, epic, fhir, mychart, mdanderson, medications, labs, vitals, appointments, karen]
---

# My Health Data (MD Anderson / Epic MyChart)
**Status: FULLY WORKING.** Credentials saved, auto-refreshes via cron. Just fetch and answer.

## Pitfall: HERMES_HOME overrides Path.home()

`HERMES_HOME=/home/drewp/.hermes/profiles/asset` overrides the shell `HOME` variable to `/home/drewp/.hermes/profiles/asset/home`. Scripts using `Path.home()` resolve to the wrong location.

**The fix:** `fetch_health.py` uses absolute paths `/home/drewp/.epic-fhir/credentials.json` and `/home/drewp/.epic-fhir/health_cache.json` instead of `Path.home() / ".epic-fhir/..."`. Keep absolute paths — never revert to `Path.home()` for credential or cache paths in the asset profile.

Real credential location: `/home/drewp/.epic-fhir/` (outside the Hermes profile dir)

## Lab Interpretation Reference

See `references/lab-interpretation.md` for Karen's lab patterns, normal ranges, and flagged lab response format.
Everything is set up. Just fetch and answer.

## When to use this skill

Use whenever Drew asks anything about:
- Karen's medications, conditions, diagnoses
- Lab results, blood work, light chains, CBC, IgG, free kappa/lambda
- Vital signs (blood pressure, weight, etc.)
- Upcoming appointments
- Allergies
- Procedures or past visits (bone marrow biopsies, echocardiograms)
- Care team / doctors at MD Anderson
- Bone marrow results, myeloma markers

## How to fetch health data

```bash
python3 ~/.hermes/profiles/asset/skills/my-health/scripts/fetch_health.py
```

This reads from a local cache (instant, <0.1s). Returns JSON with:
`patient`, `conditions`, `medications`, `allergies`, `vitals`, `labs`, `lab_trends`, `flagged_labs`, `procedures`, `upcoming_appointments`, `care_team`, `diagnostic_reports`, `immunizations`, `family_history`, `insurance`

## How to respond

- Explain everything like you're talking to a smart 10-year-old. No jargon. No acronyms without explanation.
- Never show raw JSON, field names, file paths, or code to Drew
- Lead with what's relevant to his question
- ALWAYS translate medical terms into plain English. Examples:
  - "Hemoglobin" → "the part of blood that carries oxygen"
  - "IgG" → "one of the main antibodies (proteins that fight infection)"
  - "Creatinine" → "a waste product the kidneys are supposed to filter out"
  - "Beta-2 Microglobulin" → "a protein — when it's high it means myeloma is more active"
  - "Free Kappa/Lambda ratio" → "two proteins made by the cancer cells — doctors use the ratio to track if the myeloma is growing or shrinking"
  - "CBC" → "a basic blood test that checks red cells, white cells, and platelets"
- For flagged labs: say what's high or low, what that thing does in the body, and what high/low means in plain words
- For myeloma markers: explain the trend (getting better, getting worse, stable) in one sentence
- If data is empty say "I don't see any X on file at MD Anderson"
- Never diagnose or give medical advice — just report and explain the data in everyday language
- Format: short paragraphs, no bullet soup, no medical report style. Talk like a person.

## Patient context

- Patient: Karen Pullen (Drew's grandmother), DOB 1947-07-17
- Diagnosis: Multiple myeloma
- Primary oncologist: Gregory Kaufman (Lymphoma and Myeloma), Neeraj Saini (Stem Cell Transplant)
- Allergy: Penicillins
- Recent procedure: Bone Marrow Biopsy May 2026

## If cache is stale / token expired

The `_warning` field in the JSON will say data is stale. Tell Drew:
"Your health data connection expired — you'll get a Telegram link to reconnect in a few minutes."

Do NOT tell Drew to run scripts or paste commands. The cron handles it automatically.
