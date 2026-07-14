#!/usr/bin/env python3
"""
Apply CORS settings to ALL upstream API pods so the unified UI pod can reach them.

Discovers pods via GET /v3/pods, filters for upstream API pods (pod_id ends
with 'api' and image contains 'upstream-docker-pods'), then patches each one.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/update_cors_all.py

Optional env vars:
    TAPIS_BASE_URL=https://portals.tapis.io
    CORS_ORIGIN=https://upstreamdevelop.pods.portals.tapis.io
    DRY_RUN=1   (print what would be changed without applying)
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
PODS_DOMAIN = BASE_URL.replace("https://", "pods.")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://upstreamdevelop.pods.portals.tapis.io")
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
UPSTREAM_API_IMAGE = "upstream-docker-pods"

CORS_METHODS = ["GET", "POST", "OPTIONS", "DELETE", "PUT", "HEAD", "PATCH"]
CORS_HEADERS = [
    "content-type",
    "authorization",
    "x-tapis-token",
    "x-tapis-tenant",
    "x-tapis-username",
    "x-tapis-site",
]

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} to {BASE_URL} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
token = t.access_token.access_token
print("Token acquired.\n")

hdrs = {"X-Tapis-Token": token, "Content-Type": "application/json", "Accept": "application/json"}

# Discover all upstream API pods
r = requests.get(f"{BASE_URL}/v3/pods", headers=hdrs, timeout=30)
if not r.ok:
    print(f"ERROR listing pods: {r.status_code}: {r.text}")
    sys.exit(1)

all_pods = r.json().get("result", [])
api_pods = [
    p for p in all_pods
    if p.get("pod_id", "").endswith("api")
    and (
        p.get("image") is None
        or UPSTREAM_API_IMAGE in (p.get("image") or "")
    )
]

if not api_pods:
    print("No upstream API pods found.")
    sys.exit(0)

print(f"Found {len(api_pods)} upstream API pod(s):")
for p in api_pods:
    print(f"  {p['pod_id']}  ({p.get('status', '?')})")
print()

if DRY_RUN:
    print("DRY RUN — no changes will be made.\n")

errors = []
for pod in api_pods:
    pod_id = pod["pod_id"]
    net = pod.get("networking", {}).get("default", {})
    protocol = net.get("protocol", "http")
    port = net.get("port", 8000)
    url = net.get("url", f"{pod_id}.{PODS_DOMAIN}")

    current_origins = net.get("cors_allow_origins", [])
    if CORS_ORIGIN in current_origins:
        print(f"  {pod_id}: already has {CORS_ORIGIN} — skipping.")
        continue

    print(f"  {pod_id}: granting APPROVEDADMIN permission ...")
    if not DRY_RUN:
        r = requests.post(
            f"{BASE_URL}/v3/pods/{pod_id}/permissions",
            headers=hdrs,
            json={"user": os.environ["TAPIS_USERNAME"], "level": "APPROVEDADMIN"},
            timeout=30,
        )
        if not r.ok:
            print(f"    WARNING: permission grant failed ({r.status_code}): {r.text}")
        else:
            print(f"    Permission granted.")

    print(f"  {pod_id}: adding {CORS_ORIGIN} to cors_allow_origins ...")

    if DRY_RUN:
        continue

    payload = {
        "networking": {
            "default": {
                "protocol": protocol,
                "port": port,
                "url": url,
                "cors_allow_origins": current_origins + [CORS_ORIGIN],
                "cors_allow_methods": CORS_METHODS,
                "cors_allow_headers": CORS_HEADERS,
                "cors_allow_credentials": False,
            }
        }
    }

    r = requests.put(f"{BASE_URL}/v3/pods/{pod_id}", headers=hdrs, json=payload, timeout=30)
    if not r.ok:
        print(f"    ERROR: {r.status_code}: {r.text}")
        errors.append(pod_id)
    else:
        print(f"    Done.")

print()
if errors:
    print(f"Failed pods: {errors}")
    sys.exit(1)
elif not DRY_RUN:
    print(f"All pods updated with CORS origin: {CORS_ORIGIN}")
    print("Note: pods are NOT restarted — CORS config applies without a restart.")
