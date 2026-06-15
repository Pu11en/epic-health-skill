#!/bin/bash
# Check if MD Anderson has activated karen3
URL="https://epicproxy.et0909.epichosted.com/APIProxyPRD/oauth2/authorize?response_type=code&client_id=60e43f3d-3211-4d50-bcab-c4bd1e11cad6&redirect_uri=https%3A%2F%2Fpu11en.github.io%2Fepic-oauth-callback%2F&scope=openid&state=check123"

RESPONSE=$(curl -s -L "$URL" -o /tmp/epic_check.html -w "%{http_code}")

if grep -q "MyChart" /tmp/epic_check.html 2>/dev/null || grep -q "login" /tmp/epic_check.html 2>/dev/null; then
  echo "✅ ACTIVATED — MD Anderson is ready. Run setup_auth.py to connect."
elif grep -q "OAuth2 Error" /tmp/epic_check.html 2>/dev/null; then
  echo "⏳ NOT YET — Still waiting for MD Anderson to activate (up to 48hrs from ~midnight)"
else
  echo "❓ Unknown response (HTTP $RESPONSE)"
fi
