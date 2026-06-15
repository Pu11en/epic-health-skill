#!/bin/bash
# Runs every 50 min via cron to keep health cache fresh while token is valid.
# If token is expired, does nothing (bot will prompt re-auth on next question).
LOG="$HOME/.epic-fhir/refresh.log"
python3 "$HOME/.hermes/profiles/asset/skills/my-health/scripts/fetch_health.py" --full-refresh >> "$LOG" 2>&1
echo "[$(date)] cache refresh done (exit $?)" >> "$LOG"
