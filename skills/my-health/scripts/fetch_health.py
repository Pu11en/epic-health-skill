#!/usr/bin/env python3
"""Fetch Drew's health data from Epic FHIR. Handles token refresh automatically."""
import json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path

CRED_FILE = Path("/home/drewp/.epic-fhir/credentials.json")
CACHE_FILE = Path("/home/drewp/.epic-fhir/health_cache.json")
CACHE_MAX_AGE = 23 * 3600  # serve cache if under 23 hours old
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
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "entry": []}
    except Exception as e:
        return {"error": str(e), "entry": []}

def entries(token, base, path):
    return [e["resource"] for e in fetch(token, base, path).get("entry", [])]

def entries_all(token, url, max_pages=999):
    """Follow pagination links and return all resources across pages (capped at max_pages)."""
    resources = []
    pages = 0
    while url and pages < max_pages:
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
            bundle = json.loads(urllib.request.urlopen(req, timeout=20).read())
        except Exception:
            break
        for e in bundle.get("entry", []):
            resources.append(e.get("resource", {}))
        pages += 1
        next_url = None
        for link in bundle.get("link", []):
            if link.get("relation") == "next":
                next_url = link.get("url")
                break
        url = next_url
    return resources

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

    # Labs — paginate all pages (slow but complete; called by cron, not bot queries)
    labs_raw = entries_all(token, f"{base}/Observation?patient={p}&category=laboratory&_count=50")
    labs = {}
    lab_trends = {}
    flagged = []
    for r in labs_raw:
        name = r.get("code", {}).get("text", "")
        val = r.get("valueQuantity", {})
        interp_list = r.get("interpretation", [])
        interp = interp_list[0].get("text", "") if interp_list else ""
        ref_range = ""
        if r.get("referenceRange"):
            rr = r["referenceRange"][0]
            low = rr.get("low", {}).get("value")
            high = rr.get("high", {}).get("value")
            unit = rr.get("low", rr.get("high", {})).get("unit", "")
            if low is not None and high is not None:
                ref_range = f"normal {low}-{high} {unit}".strip()
            elif high is not None:
                ref_range = f"normal <{high} {unit}".strip()
        date = r.get("effectiveDateTime", "")[:10]
        if name and val.get("value") is not None:
            entry = f"{val['value']} {val.get('unit', '')}".strip()
            if interp:
                entry += f" [{interp}]"
            if ref_range:
                entry += f" — {ref_range}"
            if date:
                entry += f" (as of {date})"
            if name not in labs:
                labs[name] = entry
                if interp and interp.upper() in ("H", "L", "HH", "LL", "HIGH", "LOW", "CRITICAL HIGH", "CRITICAL LOW", "A", "ABNORMAL"):
                    flagged.append(f"{name}: {entry}")
            if name not in lab_trends:
                lab_trends[name] = []
            if len(lab_trends[name]) < 6:
                lab_trends[name].append({"date": date, "value": f"{val['value']} {val.get('unit','')}".strip()})
    result["labs"] = labs
    result["lab_trends"] = {k: v for k, v in lab_trends.items() if len(v) > 1}
    result["flagged_labs"] = flagged

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

    # Diagnostic reports — fetch with included result Observations for actual values
    import base64
    diag_resp = fetch(token, base, f"DiagnosticReport?patient={p}&_count=50&_sort=-date&_include=DiagnosticReport:result")
    diag_obs_map = {}
    diag_reports = []
    all_entries = diag_resp.get("entry", [])
    for e in all_entries:
        r = e.get("resource", {})
        if r.get("resourceType") == "Observation":
            obs_id = r.get("id", "")
            name = r.get("code", {}).get("text", "")
            val = r.get("valueQuantity", {})
            val_str = r.get("valueString", "")
            val_cc = r.get("valueCodeableConcept", {}).get("text", "")
            if obs_id and name:
                if val.get("value") is not None:
                    diag_obs_map[obs_id] = f"{val['value']} {val.get('unit','')}"
                elif val_str:
                    diag_obs_map[obs_id] = val_str
                elif val_cc:
                    diag_obs_map[obs_id] = val_cc

    seen_reports = set()
    for e in all_entries:
        r = e.get("resource", {})
        if r.get("resourceType") != "DiagnosticReport":
            continue
        title = r.get("code", {}).get("text", "")
        date = r.get("effectiveDateTime", r.get("issued", ""))[:10]
        status = r.get("status", "")
        conclusion = r.get("conclusion", "")
        key = f"{title}:{date}"
        if not title or key in seen_reports:
            continue
        seen_reports.add(key)
        presented = []
        for pr in r.get("presentedForm", []):
            if pr.get("contentType") == "text/plain" and pr.get("data"):
                try:
                    presented.append(base64.b64decode(pr["data"]).decode("utf-8", errors="ignore"))
                except Exception:
                    pass
        result_values = {}
        for ref in r.get("result", []):
            ref_id = ref.get("reference", "").split("/")[-1]
            if ref_id in diag_obs_map:
                ref_name = ref.get("display", ref_id)
                result_values[ref_name] = diag_obs_map[ref_id]
        entry = {"title": title, "date": date, "status": status}
        if conclusion:
            entry["conclusion"] = conclusion
        if presented:
            entry["text"] = presented[0][:3000]
        if result_values:
            entry["results"] = result_values
        diag_reports.append(entry)
    result["diagnostic_reports"] = diag_reports

    # Immunizations
    imm_raw = entries(token, base, f"Immunization?patient={p}&_count=50")
    result["immunizations"] = [
        {"vaccine": r.get("vaccineCode", {}).get("text", ""), "date": r.get("occurrenceDateTime", "")[:10]}
        for r in imm_raw if r.get("vaccineCode", {}).get("text")
    ]

    # Clinical documents (notes, summaries)
    docs_raw = entries(token, base, f"DocumentReference?patient={p}&_count=20")
    documents = []
    for r in docs_raw:
        title = r.get("description") or r.get("type", {}).get("text", "")
        date = r.get("date", "")[:10]
        for content in r.get("content", []):
            att = content.get("attachment", {})
            url = att.get("url", "")
            ctype = att.get("contentType", "")
            if title:
                documents.append({"title": title, "date": date, "type": ctype, "url": url})
                break
    result["documents"] = documents

    # Family history
    fhx_raw = entries(token, base, f"FamilyMemberHistory?patient={p}&_count=50")
    family_hx = []
    for r in fhx_raw:
        relation = r.get("relationship", {}).get("text", "")
        for cond in r.get("condition", []):
            condition = cond.get("code", {}).get("text", "")
            if relation and condition:
                family_hx.append(f"{relation}: {condition}")
    result["family_history"] = family_hx

    # Goals of care
    goals_raw = entries(token, base, f"Goal?patient={p}&_count=20")
    result["goals"] = [
        r.get("description", {}).get("text", "") for r in goals_raw
        if r.get("description", {}).get("text")
    ]

    # Insurance / coverage
    coverage_raw = entries(token, base, f"Coverage?patient={p}&_count=10")
    coverage = []
    for r in coverage_raw:
        payor = r.get("payor", [{}])[0].get("display", "")
        plan = r.get("class", [{}])[0].get("name", "") if r.get("class") else ""
        status = r.get("status", "")
        if payor:
            coverage.append({"payor": payor, "plan": plan, "status": status})
    result["insurance"] = coverage

    result["_fetched_at"] = time.strftime("%Y-%m-%d %H:%M")
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

def main():
    # Bot queries always serve from cache — fast, no API call needed
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text())
        age_secs = time.time() - time.mktime(time.strptime(cache.get("_fetched_at", "2000-01-01 00:00"), "%Y-%m-%d %H:%M"))
        if age_secs < CACHE_MAX_AGE:
            cache["_from_cache"] = True
            cache["_cache_age_hours"] = round(age_secs / 3600, 1)
            print(json.dumps(cache, indent=2))
            return

    # No fresh cache — check if we can do a live fetch
    if not CRED_FILE.exists():
        print(json.dumps({"error": "no_creds", "message": "Not authenticated. Run setup_auth.py first."}))
        return

    creds = json.loads(CRED_FILE.read_text())
    token_expired = time.time() > creds.get("expires_at", 0)
    no_refresh = not creds.get("refresh_token")

    if token_expired and no_refresh:
        msg = "Health data is stale and the token expired. Tell Drew to run: python3 ~/.hermes/profiles/asset/skills/my-health/scripts/setup_auth.py"
        if CACHE_FILE.exists():
            cache = json.loads(CACHE_FILE.read_text())
            age_h = round((time.time() - time.mktime(time.strptime(cache.get("_fetched_at","2000-01-01 00:00"),"%Y-%m-%d %H:%M")))/3600,1)
            cache["_from_cache"] = True
            cache["_cache_age_hours"] = age_h
            cache["_warning"] = f"Data is {age_h}h old. Token expired — re-auth needed for fresh data."
            print(json.dumps(cache, indent=2))
        else:
            print(json.dumps({"error": "token_expired", "message": msg}))
        return

    run()

if __name__ == "__main__":
    # --full-refresh flag used by cron: always hits API, writes cache
    if len(sys.argv) > 1 and sys.argv[1] == "--full-refresh":
        run()
    else:
        main()
