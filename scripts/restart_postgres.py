#!/usr/bin/env python3
"""
Check cert status on upstreamdeveloppostgres and restart it to re-provision networking cert.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/restart_postgres.py
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
PG_POD_ID = os.environ.get("PG_POD_ID", "upstreamdeveloppostgres")

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
hdrs = {"X-Tapis-Token": t.access_token.access_token, "Content-Type": "application/json", "Accept": "application/json"}

r = requests.get(f"{BASE_URL}/v3/pods/{PG_POD_ID}", headers=hdrs, timeout=30)
if not r.ok:
    print(f"ERROR: {r.status_code}: {r.text}")
    sys.exit(1)

pod = r.json()["result"]
net = pod.get("networking", {}).get("default", {})

print(f"\n{PG_POD_ID} networking cert status:")
print(f"  networking_live: {pod.get('networking_live')}")
print(f"  cert_ready:      {net.get('cert_ready')}")
print(f"  cert_state:      {net.get('cert_state')}")
print(f"  cert_ready_at:   {net.get('cert_ready_at')}")
print()

r = requests.put(
    f"{BASE_URL}/v3/pods/{PG_POD_ID}",
    headers=hdrs,
    json={"status_requested": "RESTART"},
    timeout=30,
)
if not r.ok:
    print(f"ERROR restarting: {r.status_code}: {r.text}")
    sys.exit(1)

print(f"Restarting {PG_POD_ID} — this re-provisions the networking cert.")
print(f"Wait ~3 min then run: python3 scripts/check_pod_status.py")
