#!/usr/bin/env python3
"""One-time auth setup for Epic MyChart (MD Anderson). Stores tokens locally."""
import json, os, sys, time, urllib.request, urllib.parse, http.server, threading, webbrowser, secrets
from pathlib import Path

CRED_DIR = Path.home() / ".epic-fhir"
CRED_FILE = CRED_DIR / "credentials.json"

CLIENT_ID = "60e43f3d-3211-4d50-bcab-c4bd1e11cad6"
REDIRECT_URI = "https://pu11en.github.io/epic-oauth-callback/"
AUTH_URL = "https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/authorize"
TOKEN_URL = "https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/token"
FHIR_BASE = "https://fhir.mdanderson.org/FHIR/api/FHIR/R4"

SCOPES = " ".join([
    "patient/Patient.read",
    "patient/Condition.read",
    "patient/MedicationRequest.read",
    "patient/AllergyIntolerance.read",
    "patient/Observation.read",
    "patient/Procedure.read",
    "patient/DiagnosticReport.read",
    "patient/Appointment.read",
    "patient/CareTeam.read",
    "patient/DocumentReference.read",
    "openid", "fhirUser", "offline_access",
])

state = secrets.token_hex(16)
params = urllib.parse.urlencode({
    "response_type": "code",
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "scope": SCOPES,
    "state": state,
})

auth_link = f"{AUTH_URL}?{params}"

print("=" * 60)
print("EPIC MYCHART AUTHENTICATION SETUP")
print("=" * 60)
print()
print("1. Open this URL in your browser:")
print()
print(f"   {auth_link}")
print()
print("2. Log in with your MD Anderson MyChart credentials")
print()
print("3. After login, the page will show an auth code.")
print("   Copy it and paste it here.")
print()

code = input("Paste auth code here: ").strip()

print("\nExchanging code for tokens...")
data = urllib.parse.urlencode({
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": REDIRECT_URI,
    "client_id": CLIENT_ID,
}).encode()

req = urllib.request.Request(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
resp = json.loads(urllib.request.urlopen(req).read())

if "access_token" not in resp:
    print("Error:", resp)
    sys.exit(1)

CRED_DIR.mkdir(exist_ok=True)
creds = {
    "access_token": resp["access_token"],
    "refresh_token": resp.get("refresh_token", ""),
    "expires_at": time.time() + resp.get("expires_in", 3600) - 60,
    "patient_id": resp.get("patient", ""),
    "client_id": CLIENT_ID,
    "token_url": TOKEN_URL,
    "fhir_base": FHIR_BASE,
}
CRED_FILE.write_text(json.dumps(creds, indent=2))
os.chmod(CRED_FILE, 0o600)

print(f"\nSuccess! Tokens saved to {CRED_FILE}")
print(f"Patient ID: {creds['patient_id']}")
print("\nYou can now ask your agent about your health data.")
