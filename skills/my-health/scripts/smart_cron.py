#!/usr/bin/env python3
"""
Runs every 5 min via cron.
- Token fresh: rebuild cache silently
- Token expiring (<15 min): send Telegram alert with auth link
- Token expired: serve stale cache, resend Telegram if not alerted recently
- Code available on relay: auto-exchange and rebuild
"""
import json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path

CRED_FILE     = Path("/home/drewp/.epic-fhir/credentials.json")
CACHE_FILE    = Path("/home/drewp/.epic-fhir/health_cache.json")
STATE_FILE    = Path("/home/drewp/.epic-fhir/cron_state.json")
LOG_FILE      = Path("/home/drewp/.epic-fhir/refresh.log")
SCRIPTS       = Path(__file__).parent

RELAY_URL     = os.environ.get("EPIC_RELAY_URL", "")
RELAY_SECRET  = os.environ.get("EPIC_RELAY_SECRET", "")
TG_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID    = os.environ.get("EPIC_TG_CHAT_ID", "7414639817")

CLIENT_ID     = "60e43f3d-3211-4d50-bcab-c4bd1e11cad6"
REDIRECT_URI  = "https://pu11en.github.io/epic-oauth-callback/"
TOKEN_URL     = "https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/token"
AUTH_URL      = (
    "https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/authorize"
    f"?response_type=code&client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    "&scope=openid&state=auto"
)

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s))

def send_telegram(msg):
    if not TG_TOKEN:
        log("No TELEGRAM_BOT_TOKEN — skipping Telegram alert")
        return False
    try:
        data = json.dumps({"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        log("Telegram alert sent")
        return True
    except Exception as e:
        log(f"Telegram send failed: {e}")
        return False

def poll_relay_for_code():
    if not RELAY_URL or not RELAY_SECRET:
        return None
    try:
        req = urllib.request.Request(
            f"{RELAY_URL}/code",
            headers={"x-relay-secret": RELAY_SECRET}
        )
        resp = urllib.request.urlopen(req, timeout=10)
        if resp.status == 200:
            data = json.loads(resp.read())
            return data.get("code")
    except Exception:
        pass
    return None

def exchange_code(code):
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if "access_token" not in resp:
        log(f"Token exchange failed: {resp}")
        return False
    creds = json.loads(CRED_FILE.read_text()) if CRED_FILE.exists() else {}
    creds.update({
        "access_token": resp["access_token"],
        "expires_at": time.time() + resp.get("expires_in", 3600) - 60,
        "patient_id": resp.get("patient", creds.get("patient_id", "")),
        "client_id": CLIENT_ID,
        "token_url": TOKEN_URL,
        "fhir_base": creds.get("fhir_base", "https://fhir.mdanderson.org/FHIR/api/FHIR/R4"),
    })
    CRED_FILE.write_text(json.dumps(creds, indent=2))
    CRED_FILE.chmod(0o600)
    log("Token saved from relay code")
    return True

def rebuild_cache():
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "fetch_health.py"), "--full-refresh"],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode == 0:
        log("Cache rebuilt")
    else:
        log(f"Cache rebuild failed: {result.stderr[:200]}")

def main():
    state = load_state()
    creds = json.loads(CRED_FILE.read_text()) if CRED_FILE.exists() else {}
    now = time.time()
    expires_at = creds.get("expires_at", 0)
    time_left = expires_at - now

    # Always check relay first — if user just logged in, grab the code
    code = poll_relay_for_code()
    if code:
        log(f"Got code from relay, exchanging...")
        if exchange_code(code):
            rebuild_cache()
            state["last_alerted"] = 0  # reset alert state
            save_state(state)
            return

    if time_left > 15 * 60:
        # Token fresh — rebuild cache
        rebuild_cache()
        state["last_alerted"] = 0
        save_state(state)

    elif time_left > 0:
        # Expiring soon — alert once
        last_alert = state.get("last_alerted", 0)
        if now - last_alert > 50 * 60:  # don't spam
            send_telegram(
                f"⚕️ <b>Health data token expiring in {int(time_left/60)} min</b>\n\n"
                f"Tap to reconnect (MFA required, takes 30 sec):\n{AUTH_URL}"
            )
            state["last_alerted"] = now
            save_state(state)
        # Still rebuild with current token while we can
        rebuild_cache()

    else:
        # Token expired — send alert if not sent recently
        last_alert = state.get("last_alerted", 0)
        if now - last_alert > 6 * 3600:  # remind every 6 hours
            cache_age_h = ""
            if CACHE_FILE.exists():
                c = json.loads(CACHE_FILE.read_text())
                age = now - time.mktime(time.strptime(c.get("_fetched_at","2000-01-01 00:00"), "%Y-%m-%d %H:%M"))
                cache_age_h = f" (data is {round(age/3600,1)}h old)"
            send_telegram(
                f"⚕️ <b>Health data needs reconnecting{cache_age_h}</b>\n\n"
                f"Tap to reconnect (takes 30 sec):\n{AUTH_URL}"
            )
            state["last_alerted"] = now
            save_state(state)
        log("Token expired, serving stale cache")

if __name__ == "__main__":
    main()
