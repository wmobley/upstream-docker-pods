#!/usr/bin/env python3
"""
Print status and recent logs for all upstream develop pods.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/check_pod_status.py
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
POD_IDS = os.environ.get("POD_IDS", "upstreamdeveloppostgres,upstreamdevelopapi,upstreamdevelop").split(",")

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} to {BASE_URL} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
token = t.access_token.access_token

hdrs = {"X-Tapis-Token": token, "Accept": "application/json"}

for pod_id in POD_IDS:
    r = requests.get(f"{BASE_URL}/v3/pods/{pod_id}", headers=hdrs, timeout=30)
    if not r.ok:
        print(f"\n{pod_id}: ERROR {r.status_code}: {r.text}")
        continue

    pod = r.json()["result"]
    status = pod.get("status", "?")
    container = pod.get("status_container", {})
    phase = container.get("phase", "?")
    ready = container.get("ready", "?")
    restarts = container.get("restart_count", "?")
    message = container.get("message", "")
    start_time = container.get("start_time", "")

    print(f"\n{'='*60}")
    print(f"Pod: {pod_id}")
    print(f"  Status:        {status}")
    print(f"  Phase:         {phase}")
    print(f"  Ready:         {ready}")
    print(f"  Restarts:      {restarts}")
    print(f"  Start time:    {start_time}")
    if message:
        print(f"  Message:       {message}")

    # Fetch logs
    log_r = requests.get(f"{BASE_URL}/v3/pods/{pod_id}/logs", headers=hdrs, timeout=30)
    if log_r.ok:
        logs = log_r.json().get("result", {}).get("logs", "")
        if logs:
            tail = "\n".join(logs.splitlines()[-40:])
            print(f"\n  --- Last 40 log lines ---\n{tail}")
        else:
            print("  (no logs)")
    else:
        print(f"  (logs unavailable: {log_r.status_code})")
