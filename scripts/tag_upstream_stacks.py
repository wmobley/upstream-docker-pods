#!/usr/bin/env python3
"""
Mark upstream API pods by prefixing their description with '[upstream]'.
Tapis Pods does not support a writable tags field, so description is used
as the discovery marker.

The unified UI and CORS scripts filter for API pods whose description
starts with '[upstream]'.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/tag_upstream_stacks.py

Optional:
    DRY_RUN=1   print what would change without applying
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
MARKER = "[upstream]"

# Stack ID → human-readable display name shown in the unified UI dropdown.
UPSTREAM_STACKS = {
    "flux":           "SETx Flux Tower",
    "upstream":       "UpStream Base System",
    "upstreamdevelop": "Development",
    "vital":          "Virtual Institute for Temporal and Additive Learning (VITAL)",
}

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
token = t.access_token.access_token
print("Token acquired.\n")

hdrs = {"X-Tapis-Token": token, "Content-Type": "application/json", "Accept": "application/json"}

r = requests.get(f"{BASE_URL}/v3/pods", headers=hdrs, timeout=30)
if not r.ok:
    print(f"ERROR listing pods: {r.status_code}: {r.text}")
    sys.exit(1)

all_pods = {p["pod_id"]: p for p in r.json().get("result", [])}

if DRY_RUN:
    print("DRY RUN — no changes will be made.\n")

errors = []
for stack, display_name in UPSTREAM_STACKS.items():
    pod_id = f"{stack}api"
    pod = all_pods.get(pod_id)
    if not pod:
        print(f"  WARNING: {pod_id} not found — skipping")
        continue

    new_desc = f"{MARKER} {display_name}"
    current_desc = (pod.get("description") or "").strip()
    if current_desc == new_desc:
        print(f"  {pod_id}: already set — skipping")
        continue

    print(f"  {pod_id}: description → \"{new_desc}\"")
    if DRY_RUN:
        continue

    r = requests.put(
        f"{BASE_URL}/v3/pods/{pod_id}",
        headers=hdrs,
        json={"description": new_desc},
        timeout=30,
    )
    if not r.ok:
        print(f"    ERROR: {r.status_code}: {r.text}")
        errors.append(pod_id)
    else:
        print(f"    Done.")

print()
if errors:
    print(f"Failed: {errors}")
    sys.exit(1)
elif not DRY_RUN:
    print("Done. Discovery will now filter by description starting with '[upstream]'.")
