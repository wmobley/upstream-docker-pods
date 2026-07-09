#!/usr/bin/env python3
"""
Update the upstreamdevelopapi pod startup command to include the DB retry loop.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/update_develop_api_command.py
"""
import os
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
POD_ID = "upstreamdevelopapi"
STARTUP_COMMAND = [
    "/bin/bash",
    "-c",
    "until alembic upgrade heads; do echo 'Waiting for DB...'; sleep 10; done && uvicorn app.main:app --reload --host 0.0.0.0",
]

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} to {BASE_URL} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
token = t.access_token.access_token
print("Token acquired.")

headers = {
    "X-Tapis-Token": token,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

print(f"Fetching current config for {POD_ID} ...")
r = requests.get(f"{BASE_URL}/v3/pods/{POD_ID}", headers=headers, timeout=30)
if not r.ok:
    raise RuntimeError(f"GET /pods/{POD_ID} → {r.status_code}: {r.text}")
pod = r.json()["result"]
print(f"  Current command: {pod.get('command')}")

payload = {
    "image": pod.get("image"),
    "description": pod.get("description"),
    "command": STARTUP_COMMAND,
    "arguments": pod.get("arguments"),
    "environment_variables": pod.get("environment_variables") or {},
    "secret_map": pod.get("secret_map") or {},
    "status_requested": "RESTART",
    "volume_mounts": pod.get("volume_mounts") or {},
    "time_to_stop_default": pod.get("time_to_stop_default", -1),
    "networking": pod.get("networking") or {},
    "resources": pod.get("resources") or {},
}

print(f"Updating {POD_ID} with retry-loop startup command ...")
r = requests.put(f"{BASE_URL}/v3/pods/{POD_ID}", headers=headers, json=payload, timeout=30)
if not r.ok:
    raise RuntimeError(f"PUT /pods/{POD_ID} → {r.status_code}: {r.text}")
print(f"  Status: {r.json().get('status')}")
print("Done. Pod will restart with the new command.")
