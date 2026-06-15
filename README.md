# epic-health-skill

A Hermes agent skill that connects to Epic MyChart via FHIR R4 and answers natural language questions about your health data.

## What it does

Ask your agent things like:
- "what are my current medications?"
- "show me my latest lab results"
- "do I have any upcoming appointments?"
- "what conditions are on my problem list?"
- "who's on my care team?"

The agent pulls real-time data from your MyChart account and answers in plain English.

## Structure

```
skills/my-health/
  SKILL.md              — Hermes skill definition
  scripts/
    setup_auth.py       — One-time OAuth setup (run this first)
    fetch_health.py     — Fetches all health data from FHIR API

auth/
  epic-auth-setup.sh    — Bash-based auth setup alternative

callback/
  index.html            — OAuth callback page (hosted on GitHub Pages)
```

## Setup

### 1. Register an Epic app
- Go to fhir.epic.com → create a Patient-facing app
- Set Automatic Client Distribution: USCDI v1
- Redirect URI: your GitHub Pages URL (e.g. `https://yourusername.github.io/epic-oauth-callback/`)
- Mark Ready for Production

### 2. Host the callback page
Deploy `callback/index.html` to GitHub Pages.

### 3. Update credentials in setup_auth.py
Edit `CLIENT_ID`, `REDIRECT_URI`, `AUTH_URL`, `TOKEN_URL`, `FHIR_BASE` to match your hospital and app.

### 4. Run auth setup
```bash
python3 skills/my-health/scripts/setup_auth.py
```
Opens a browser login → paste the auth code → tokens stored at `~/.epic-fhir/credentials.json`.

### 5. Install the skill in your Hermes agent
Copy `skills/my-health/` to your Hermes profile:
```bash
cp -r skills/my-health/ ~/.hermes/profiles/<your-profile>/skills/
```

## Tested with
- MD Anderson Cancer Center (Epic)
- Epic sandbox (test patient: fhirderrick / epicepic1)

## Epic app details (for reference)
- Sandbox auth: `https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize`
- No `aud` parameter needed
- Scope format: `patient/Patient.read openid fhirUser offline_access`
