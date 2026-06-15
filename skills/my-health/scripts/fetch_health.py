#!/usr/bin/env python3
"""Fetch Drew's health data from Epic FHIR. Handles token refresh automatically."""
import json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path

CRED_FILE = Path.home() / ".epic-fhir" / "credentials.json"
BASE = "https://fhir.mdanderson.org/FHIR/api/FHIR/R4"
SANDBOX_BASE = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"
TOKEN_URL = "https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/token"
SANDBOX_TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
CLIENT_ID = "60e43f3d-3211-4d50-bcab-c4bd1e11cad6"
REDIRECT_URI = "https://pu11en.github.io/epic-oauth-callback/"

def load_creds():
    if not CRED_FILE.exists():
        print(json.dumps({"error": "no_creds", "message": "Not authenticated yet. Run: hermes run asset 'set up my health data access'"}))
        sys.exit(0)
    return json.loads(CRED_FILE.read_text())

def refresh_token(creds):
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": creds["refresh_token"],
        "client_id": creds.get("client_id", CLIENT_ID),
    }).encode()
    url = creds.get("token_url", TOKEN_URL)
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = json.loads(urllib.request.urlopen(req).read())
    creds["access_token"] = resp["access_token"]
    creds["expires_at"] = time.time() + resp.get("expires_in", 3600) - 60
    if "refresh_token" in resp:
        creds["refresh_token"] = resp["refresh_token"]
    CRED_FILE.write_text(json.dumps(creds, indent=2))
    return creds

def get_token():
    creds = load_creds()
    if time.time() > creds.get("expires_at", 0):
        creds = refresh_token(creds)
    return creds["access_token"], creds.get("patient_id"), creds.get("fhir_base", BASE)

def fetch(token, base, path):
    try:
        req = urllib.request.Request(
            f"{base}/{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "entry": []}
    except Exception as e:
        return {"error": str(e), "entry": []}

def entries(token, base, path):
    return [e["resource"] for e in fetch(token, base, path).get("entry", [])]

def run():
    token, patient, base = get_token()
    p = patient

    result = {}

    # Patient demographics
    pt = fetch(token, base, f"Patient/{p}")
    if "name" in pt:
        name = pt["name"][0]
        result["patient"] = {
            "name": name.get("text") or f"{' '.join(name.get('given', []))} {name.get('family', '')}".strip(),
            "dob": pt.get("birthDate"),
            "gender": pt.get("gender"),
        }

    # Conditions
    conditions = entries(token, base, f"Condition?patient={p}&category=problem-list-item&clinical-status=active")
    result["conditions"] = [r.get("code", {}).get("text", "") for r in conditions if r.get("code", {}).get("text")]

    # Medications
    meds = entries(token, base, f"MedicationRequest?patient={p}&status=active")
    result["medications"] = [
        r.get("medicationCodeableConcept", {}).get("text") or r.get("medicationReference", {}).get("display", "")
        for r in meds
    ]

    # Allergies
    allergies = entries(token, base, f"AllergyIntolerance?patient={p}")
    result["allergies"] = [r.get("code", {}).get("text", "") for r in allergies if r.get("code", {}).get("text")]

    # Vitals (most recent)
    vitals_raw = entries(token, base, f"Observation?patient={p}&category=vital-signs&_count=20")
    vitals = {}
    for r in vitals_raw:
        name = r.get("code", {}).get("text", "")
        val = r.get("valueQuantity", {})
        comp = r.get("component", [])
        if name and name not in vitals:
            if val.get("value"):
                vitals[name] = f"{val['value']} {val.get('unit', '')}"
            elif comp:
                parts = []
                for c in comp:
                    v = c.get("valueQuantity", {})
                    if v.get("value"):
                        parts.append(f"{c.get('code',{}).get('text','')}: {v['value']} {v.get('unit','')}")
                if parts:
                    vitals[name] = ", ".join(parts)
    result["vitals"] = vitals

    # Labs (most recent unique)
    labs_raw = entries(token, base, f"Observation?patient={p}&category=laboratory&_count=30")
    labs = {}
    for r in labs_raw:
        name = r.get("code", {}).get("text", "")
        val = r.get("valueQuantity", {})
        interp = r.get("interpretation", [{}])[0].get("text", "")
        if name and name not in labs and val.get("value"):
            labs[name] = f"{val['value']} {val.get('unit', '')} {f'({interp})' if interp else ''}".strip()
    result["labs"] = labs

    # Procedures
    procs = entries(token, base, f"Procedure?patient={p}&_count=10")
    result["procedures"] = [
        {"name": r.get("code", {}).get("text", ""), "date": str(r.get("performedDateTime", ""))[:10]}
        for r in procs if r.get("code", {}).get("text")
    ]

    # Appointments
    appts = entries(token, base, f"Appointment?patient={p}&status=booked&_count=5")
    result["upcoming_appointments"] = [
        {"date": r.get("start", "")[:10], "description": r.get("description", ""), "status": r.get("status", "")}
        for r in appts
    ]

    # Care team
    teams = entries(token, base, f"CareTeam?patient={p}")
    providers = []
    for r in teams:
        for part in r.get("participant", []):
            name = part.get("member", {}).get("display", "")
            role = part.get("role", [{}])[0].get("text", "") if part.get("role") else ""
            if name:
                providers.append({"name": name, "role": role})
    result["care_team"] = providers

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    run()
