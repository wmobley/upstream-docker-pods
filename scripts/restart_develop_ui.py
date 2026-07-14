#!/usr/bin/env python3
"""
Update the upstreamdevelop UI pod env vars and restart it.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/restart_develop_ui.py

Optional env vars (defaults shown):
    TAPIS_BASE_URL=https://portals.tapis.io
    UI_POD_ID=upstreamdevelop
    VITE_TAPIS_OAUTH_CLIENT_ID=upstream-devui
    VITE_TAPIS_OAUTH_CLIENT_KEY=<leave blank to omit from pod env>
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
PODS_DOMAIN = BASE_URL.replace("https://", "pods.")
UI_POD_ID = os.environ.get("UI_POD_ID", "upstreamdevelop")
API_POD_ID = os.environ.get("API_POD_ID", f"{UI_POD_ID}api")
CLIENT_ID = os.environ.get("VITE_TAPIS_OAUTH_CLIENT_ID", "upstream-develop")
CLIENT_KEY = os.environ.get("VITE_TAPIS_OAUTH_CLIENT_KEY", "")
# Setting VITE_UPSTREAM_API_URL disables browser-side discovery and routes
# API calls directly to the develop API pod (avoids CORS on Tapis endpoints).
# Leave empty to enable discovery via nginx /tapis-proxy/ — set to a URL only
# when you want to force a specific API pod and skip discovery.
API_URL = os.environ.get("VITE_UPSTREAM_API_URL", "")

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} to {BASE_URL} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
token = t.access_token.access_token
print("Token acquired.\n")

headers = {
    "X-Tapis-Token": token,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Fetch current pod config
r = requests.get(f"{BASE_URL}/v3/pods/{UI_POD_ID}", headers=headers, timeout=30)
if not r.ok:
    print(f"ERROR fetching pod {UI_POD_ID}: {r.status_code}: {r.text}")
    sys.exit(1)

pod = r.json().get("result", {})
env = pod.get("environment_variables") or {}

# Patch env vars
env["VITE_TAPIS_OAUTH_CLIENT_ID"] = CLIENT_ID
if API_URL:
    env["VITE_UPSTREAM_API_URL"] = API_URL
elif "VITE_UPSTREAM_API_URL" in env:
    del env["VITE_UPSTREAM_API_URL"]
if CLIENT_KEY:
    env["VITE_TAPIS_OAUTH_CLIENT_KEY"] = CLIENT_KEY

print(f"Updating {UI_POD_ID} environment_variables:")
for k, v in env.items():
    masked = v[:4] + "..." if k == "VITE_TAPIS_OAUTH_CLIENT_KEY" and v else v
    print(f"  {k}={masked}")

payload = {
    "environment_variables": env,
    "status_requested": "RESTART",
}

r = requests.put(f"{BASE_URL}/v3/pods/{UI_POD_ID}", headers=headers, json=payload, timeout=30)
if not r.ok:
    print(f"ERROR updating pod: {r.status_code}: {r.text}")
    sys.exit(1)

print(f"\nPod {UI_POD_ID} restarting with VITE_TAPIS_OAUTH_CLIENT_ID={CLIENT_ID}")
print(f"Check status: {BASE_URL}/v3/pods/{UI_POD_ID}")
