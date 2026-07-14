#!/usr/bin/env python3
"""
Append ?sslmode=require to the DATABASE_URL on the upstreamdevelopapi pod
and restart it.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/patch_api_db_url.py
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
API_POD_ID = os.environ.get("API_POD_ID", "upstreamdevelopapi")

print(f"Authenticating as {os.environ['TAPIS_USERNAME']} to {BASE_URL} ...")
t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
token = t.access_token.access_token
print("Token acquired.\n")

hdrs = {"X-Tapis-Token": token, "Content-Type": "application/json", "Accept": "application/json"}

r = requests.get(f"{BASE_URL}/v3/pods/{API_POD_ID}", headers=hdrs, timeout=30)
if not r.ok:
    print(f"ERROR fetching pod: {r.status_code}: {r.text}")
    sys.exit(1)

env = r.json()["result"].get("environment_variables", {})
db_url = env.get("DATABASE_URL", "")
if not db_url:
    print("ERROR: DATABASE_URL not found in pod environment")
    sys.exit(1)

import re
new_db_url = re.sub(r'\?sslmode=\w+', '', db_url)  # remove any prior sslmode
env["DATABASE_URL"] = new_db_url

redact = lambda u: re.sub(r'(:)([^:@]+)(@)', r'\1***\3', u)
print(f"Old: {redact(db_url)}")
print(f"New: {redact(new_db_url)}")
print()

r = requests.put(
    f"{BASE_URL}/v3/pods/{API_POD_ID}",
    headers=hdrs,
    json={"environment_variables": env, "status_requested": "RESTART"},
    timeout=30,
)
if not r.ok:
    print(f"ERROR updating pod: {r.status_code}: {r.text}")
    sys.exit(1)

print(f"Pod {API_POD_ID} updated and restarting.")
print(f"Monitor: {BASE_URL}/v3/pods/{API_POD_ID}")
