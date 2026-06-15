---
name: my-health
description: "Answer Drew's questions about his real health data from MD Anderson MyChart via Epic FHIR."
version: 1.0.0
author: drewp
metadata:
  hermes:
    tags: [health, epic, fhir, mychart, mdanderson, medications, labs, vitals, appointments]
---

# My Health Data (MD Anderson / Epic MyChart)

Gives Drew real-time access to his health records from MD Anderson via Epic FHIR.

## When to use this skill

Use whenever Drew asks anything about:
- His medications, conditions, diagnoses
- Lab results, blood work, test results
- Vital signs (blood pressure, weight, etc.)
- Upcoming appointments
- Allergies
- Procedures or past visits
- His care team / doctors

## How to fetch health data

Run the fetch script and interpret the JSON result naturally:

```bash
python3 ~/.hermes/profiles/asset/skills/my-health/scripts/fetch_health.py
```

The script returns JSON with: `patient`, `conditions`, `medications`, `allergies`, `vitals`, `labs`, `procedures`, `upcoming_appointments`, `care_team`.

## How to respond

- Answer in plain English like a knowledgeable friend, not a medical robot
- Never show raw JSON or field names to Drew
- Summarize what's relevant to his question
- If data is empty/missing, say "I don't see any X on file at MD Anderson"
- Never diagnose or give medical advice — just report the data

## First-time setup (if no credentials)

If the script outputs `{"error": "no_creds", ...}`, tell Drew to run this to connect his MyChart:

```bash
python3 ~/.hermes/profiles/asset/skills/my-health/scripts/setup_auth.py
```

Then walk him through: open the URL → log in with MD Anderson MyChart → paste the code back.

Credentials are stored in `~/.epic-fhir/credentials.json` and auto-refresh. One-time setup only.

## MD Anderson endpoint info

- FHIR base: `https://fhir.mdanderson.org/FHIR/api/FHIR/R4`
- Auth: `https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/authorize`
- Token: `https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/token`
- App client ID: `60e43f3d-3211-4d50-bcab-c4bd1e11cad6`
- Callback: `https://pu11en.github.io/epic-oauth-callback/`
- Auth scope key: no `aud` parameter (causes errors), no `offline_access` until MD Anderson activates it
