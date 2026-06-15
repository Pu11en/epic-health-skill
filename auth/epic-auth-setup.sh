#!/usr/bin/env bash
# epic-auth-setup.sh
# One-time OAuth2 flow for Epic FHIR. Opens browser, catches callback, stores tokens.
export PATH="${HOME}/.local/bin:${PATH}"
JQ="${HOME}/.local/bin/jq"
#
# Required env:
#   EPIC_CLIENT_ID          — your registered app's client_id
#   EPIC_REDIRECT_URI       — must match what's registered (default http://localhost:8765/callback)
#   EPIC_FHIR_BASE          — default https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4
#   EPIC_AUTH_BASE          — default https://fhir.epic.com/interconnect-fhir-oauth/oauth2
#
# Optional env:
#   EPIC_SCOPES             — space-separated SMART scopes (default: a safe read set)
#   EPIC_ENV                — "sandbox" (default) or "production"

set -euo pipefail

EPIC_DIR="${HOME}/.epic-fhir"
CRED_FILE="${EPIC_DIR}/credentials.json"
CONFIG_FILE="${EPIC_DIR}/config.json"

# Load .env file if it exists (Hermes-style)
if [ -f "${HOME}/.hermes/profiles/asset/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.hermes/profiles/asset/.env"
  set +a
fi

# Defaults
: "${EPIC_ENV:=sandbox}"
: "${EPIC_REDIRECT_URI:=http://localhost:8766/callback}"
: "${EPIC_FHIR_BASE:=https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4}"
: "${EPIC_AUTH_BASE:=https://fhir.epic.com/interconnect-fhir-oauth/oauth2}"
: "${EPIC_SCOPES:=patient/Patient.rs patient/Observation.rs patient/MedicationRequest.rs patient/MedicationStatement.rs patient/Condition.rs patient/AllergyIntolerance.rs patient/Immunization.rs patient/Procedure.rs patient/DiagnosticReport.rs patient/Encounter.rs patient/DocumentReference.rs patient/CarePlan.rs patient/Goal.rs patient/CareTeam.rs patient/Coverage.rs patient/Appointment.rs patient/Communication.rs patient/ExplanationOfBenefit.rs launch/patient openid fhirUser offline_access}"

# Required
if [ -z "${EPIC_CLIENT_ID:-}" ]; then
  echo "ERROR: EPIC_CLIENT_ID not set."
  echo "  1. Sign up at https://fhir.epic.com"
  echo "  2. Build Apps > Create My First App > get your non-production client_id"
  echo "  3. export EPIC_CLIENT_ID=epic-app-XXXXX"
  echo "  4. Re-run this script"
  exit 1
fi

mkdir -p "${EPIC_DIR}"
chmod 700 "${EPIC_DIR}"

# Save config for future runs
cat > "${CONFIG_FILE}" <<EOF
{
  "client_id": "${EPIC_CLIENT_ID}",
  "redirect_uri": "${EPIC_REDIRECT_URI}",
  "fhir_base": "${EPIC_FHIR_BASE}",
  "auth_base": "${EPIC_AUTH_BASE}",
  "env": "${EPIC_ENV}",
  "scopes": "${EPIC_SCOPES}"
}
EOF
chmod 600 "${CONFIG_FILE}"

echo "Epic FHIR OAuth setup"
echo "  Env:        ${EPIC_ENV}"
echo "  Client ID:  ${EPIC_CLIENT_ID}"
echo "  Redirect:   ${EPIC_REDIRECT_URI}"
echo "  FHIR base:  ${EPIC_FHIR_BASE}"
echo "  Scopes:     ${EPIC_SCOPES}"
echo ""

# Generate state nonce
STATE=$(openssl rand -hex 16)

# Parse redirect URI to get port and path
REDIRECT_HOST=$(echo "${EPIC_REDIRECT_URI}" | sed -E 's|^https?://||; s|/.*$||')
REDIRECT_PORT=$(echo "${REDIRECT_HOST}" | sed -E 's|^.*:||')
REDIRECT_PATH=$(echo "${EPIC_REDIRECT_URI}" | sed -E 's|^https?://[^/]*||')
REDIRECT_HOST_ONLY=$(echo "${REDIRECT_HOST}" | sed -E 's|:.*$||')

if [ -z "${REDIRECT_PORT}" ] || [ "${REDIRECT_PORT}" = "${REDIRECT_HOST}" ]; then
  # Default to 80 if no port
  REDIRECT_PORT=80
  REDIRECT_HOST_ONLY="${REDIRECT_HOST}"
fi

# Build authorize URL
AUTHORIZE_URL="${EPIC_AUTH_BASE}/authorize"
AUTHORIZE_URL="${AUTHORIZE_URL}?response_type=code"
AUTHORIZE_URL="${AUTHORIZE_URL}&client_id=$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=''))" "${EPIC_CLIENT_ID}")"
AUTHORIZE_URL="${AUTHORIZE_URL}&redirect_uri=$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=''))" "${EPIC_REDIRECT_URI}")"
AUTHORIZE_URL="${AUTHORIZE_URL}&scope=$(python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=''))" "${EPIC_SCOPES}")"
AUTHORIZE_URL="${AUTHORIZE_URL}&state=${STATE}"
AUTHORIZE_URL="${AUTHORIZE_URL}&aud=${EPIC_FHIR_BASE}"

echo "Open this URL in a browser to authorize:"
echo "  ${AUTHORIZE_URL}"
echo ""

# Open the URL in the default browser
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${AUTHORIZE_URL}" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "${AUTHORIZE_URL}" >/dev/null 2>&1 || true
fi

# Start a tiny callback server
echo "Waiting for OAuth callback on ${EPIC_REDIRECT_URI} ..."
echo "(If the browser didn't open, paste the URL above.)"

CALLBACK_FILE=$(mktemp)
trap 'rm -f "${CALLBACK_FILE}"; pkill -f "epic-auth-callback" 2>/dev/null || true' EXIT

# Use python (always available) for a one-shot HTTP server
python3 - "${REDIRECT_PORT}" "${REDIRECT_PATH}" "${STATE}" "${CALLBACK_FILE}" <<'PYEOF' &
import http.server
import sys
import urllib.parse
import os

port = int(sys.argv[1])
path = sys.argv[2]
expected_state = sys.argv[3]
out_file = sys.argv[4]

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != path:
            self.send_response(404); self.end_headers(); return
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get('code', [None])[0]
        state = qs.get('state', [None])[0]
        err = qs.get('error', [None])[0]
        if err:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Error: {err} {qs.get('error_description', [''])[0]}".encode())
            with open(out_file, 'w') as f:
                f.write(f"ERROR={err}\n")
            return
        if state != expected_state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State mismatch - possible CSRF. Aborting.")
            with open(out_file, 'w') as f:
                f.write("ERROR=state_mismatch\n")
            return
        if not code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code in callback")
            with open(out_file, 'w') as f:
                f.write("ERROR=no_code\n")
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b"<h1>Epic auth complete.</h1><p>You can close this tab.</p>")
        with open(out_file, 'w') as f:
            f.write(f"CODE={code}\n")
    def log_message(self, *a, **k):
        pass  # quiet

server = http.server.HTTPServer(('127.0.0.1', port), Handler)
server.handle_request()  # one request
PYEOF

SERVER_PID=$!

# Wait for callback (max 5 min)
for i in {1..300}; do
  if [ -s "${CALLBACK_FILE}" ]; then break; fi
  sleep 1
done
kill "${SERVER_PID}" 2>/dev/null || true
wait "${SERVER_PID}" 2>/dev/null || true

if [ ! -s "${CALLBACK_FILE}" ]; then
  echo "ERROR: Timed out waiting for callback."
  exit 1
fi

# shellcheck disable=SC1090
source "${CALLBACK_FILE}"

if [ "${CODE:-}" = "" ] || [ "${CODE:0:1}" != "{" ]; then
  # CODE was set, ERROR not set — proceed
  :
fi

if [ -z "${CODE:-}" ]; then
  echo "ERROR: ${ERROR:-unknown}"
  exit 1
fi

echo ""
echo "Got authorization code. Exchanging for tokens ..."

# Exchange code for tokens
TOKEN_RESPONSE=$(curl -sS -X POST "${EPIC_AUTH_BASE}/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=${CODE}" \
  --data-urlencode "client_id=${EPIC_CLIENT_ID}" \
  --data-urlencode "redirect_uri=${EPIC_REDIRECT_URI}")

# Save the raw response
echo "${TOKEN_RESPONSE}" | "${JQ}" . > "${CRED_FILE}"
chmod 600 "${CRED_FILE}"

# Compute expires_at
NOW=$(date +%s)
EXPIRES_IN=$(echo "${TOKEN_RESPONSE}" | "${JQ}" -r '.expires_in // 3600')
EXPIRES_AT=$((NOW + EXPIRES_IN))

# Merge into credentials
PATIENT_ID=$(echo "${TOKEN_RESPONSE}" | "${JQ}" -r '.patient // ""')
ACCESS_TOKEN=$(echo "${TOKEN_RESPONSE}" | "${JQ}" -r '.access_token')
REFRESH_TOKEN=$(echo "${TOKEN_RESPONSE}" | "${JQ}" -r '.refresh_token // ""')
GRANTED_SCOPE=$(echo "${TOKEN_RESPONSE}" | "${JQ}" -r '.scope // ""')

"${JQ}" -n \
  --arg client_id "${EPIC_CLIENT_ID}" \
  --arg fhir_base "${EPIC_FHIR_BASE}" \
  --arg auth_base "${EPIC_AUTH_BASE}" \
  --arg patient_id "${PATIENT_ID}" \
  --arg access_token "${ACCESS_TOKEN}" \
  --arg refresh_token "${REFRESH_TOKEN}" \
  --argjson expires_at "${EXPIRES_AT}" \
  --arg granted_scope "${GRANTED_SCOPE}" \
  --arg env "${EPIC_ENV}" \
  '{
    client_id: $client_id,
    fhir_base: $fhir_base,
    auth_base: $auth_base,
    env: $env,
    patient_id: $patient_id,
    access_token: $access_token,
    refresh_token: $refresh_token,
    expires_at: $expires_at,
    granted_scope: $granted_scope
  }' > "${CRED_FILE}"
chmod 600 "${CRED_FILE}"

echo ""
echo "Saved to ${CRED_FILE}"
echo ""
echo "Patient ID:    ${PATIENT_ID}"
echo "Granted scope: ${GRANTED_SCOPE}"
echo "Access token expires: $(date -d "@${EXPIRES_AT}" 2>/dev/null || date -r "${EXPIRES_AT}")"
echo ""
echo "Test it:"
echo "  ~/.hermes/profiles/asset/skills/epic-fhir/epic-fhir-auth/scripts/epic-fhir-call.sh /Patient/${PATIENT_ID}"
