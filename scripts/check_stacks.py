#!/usr/bin/env python3
"""
Audit all upstream pods and report stack completeness.

Groups pods by prefix, checks which stacks have all three parts
(postgres, api, ui) and flags anything incomplete or orphaned.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/check_stacks.py
"""
import os
import sys
import requests
from collections import defaultdict
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
token = t.access_token.access_token
print("Token acquired.\n")

hdrs = {"X-Tapis-Token": token, "Accept": "application/json"}

r = requests.get(f"{BASE_URL}/v3/pods", headers=hdrs, timeout=30)
if not r.ok:
    print(f"ERROR: {r.status_code}: {r.text}")
    sys.exit(1)

pods = r.json().get("result", [])

# Group by stack prefix using known suffixes
SUFFIXES = ["postgres", "api", ""]  # "" = UI pod (bare stack name)

stacks = defaultdict(dict)   # prefix -> {role: pod}
orphans = []

for pod in pods:
    pod_id = pod["pod_id"]
    matched = False
    for suffix in ["postgres", "api"]:
        if pod_id.endswith(suffix) and len(pod_id) > len(suffix):
            prefix = pod_id[: -len(suffix)]
            stacks[prefix][suffix] = pod
            matched = True
            break
    if not matched:
        # Could be a bare UI pod — check if a matching api pod exists
        stacks[pod_id]["ui"] = pod

# Clean up: a "ui" entry is only a real UI pod if there's also an api in the same stack
# Remove ui entries that don't have a corresponding api
for prefix in list(stacks.keys()):
    if "ui" in stacks[prefix] and "api" not in stacks[prefix] and prefix not in {
        p[:-3] for p in stacks  # prefixes that have an api pod
    }:
        orphans.append(stacks[prefix]["ui"])
        del stacks[prefix]

UPSTREAM_IMAGE = "upstream-docker-pods"

print(f"{'STACK':<25} {'POSTGRES':<12} {'API':<12} {'UI':<12} {'UPSTREAM':<10} {'COMPLETE'}")
print("-" * 90)

complete_stacks = []
incomplete_stacks = []

for prefix in sorted(stacks.keys()):
    parts = stacks[prefix]
    has_postgres = "postgres" in parts
    has_api = "api" in parts
    has_ui = "ui" in parts

    api_image = parts.get("api", {}).get("image") or ""
    is_upstream = UPSTREAM_IMAGE in api_image if api_image else None
    upstream_label = "YES" if is_upstream else ("UNKNOWN" if is_upstream is None else "NO")

    def status(pod_dict, role):
        if role not in pod_dict:
            return "MISSING"
        s = pod_dict[role].get("status", "?")
        return s[:10]

    complete = has_postgres and has_api
    marker = "YES" if complete else "NO "

    print(
        f"{prefix:<25} {status(parts, 'postgres'):<12} {status(parts, 'api'):<12} {status(parts, 'ui') if has_ui else 'none':<12} {upstream_label:<10} {marker}"
    )
    api_tags = parts.get("api", {}).get("tags") or []
    if api_image or api_tags:
        print(f"  image: {api_image}  tags: {api_tags}")

    if complete:
        complete_stacks.append(prefix)
    else:
        incomplete_stacks.append((prefix, parts))

if orphans:
    print("\nORPHANED PODS (no matching api/postgres pair):")
    for p in orphans:
        print(f"  {p['pod_id']}  ({p.get('status', '?')})")

print(f"\nComplete stacks:   {len(complete_stacks)}")
print(f"Incomplete stacks: {len(incomplete_stacks)}")

if incomplete_stacks:
    print("\nMISSING PARTS:")
    for prefix, parts in incomplete_stacks:
        missing = [r for r in ["postgres", "api"] if r not in parts]
        print(f"  {prefix}: missing {', '.join(missing)}")
