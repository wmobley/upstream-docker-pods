#!/usr/bin/env python3
"""
Check postgres pod networking cert status and the API pod DATABASE_URL.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/check_pg_networking.py
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
PG_POD_ID = os.environ.get("PG_POD_ID", "upstreamdeveloppostgres")
API_POD_ID = os.environ.get("API_POD_ID", "upstreamdevelopapi")

t = Tapis(base_url=BASE_URL, username=os.environ["TAPIS_USERNAME"], password=os.environ["TAPIS_PASSWORD"])
t.get_tokens()
hdrs = {"X-Tapis-Token": t.access_token.access_token, "Accept": "application/json"}

# Postgres pod networking
r = requests.get(f"{BASE_URL}/v3/pods/{PG_POD_ID}", headers=hdrs, timeout=30)
if not r.ok:
    print(f"ERROR fetching {PG_POD_ID}: {r.status_code}: {r.text}")
    sys.exit(1)

pod = r.json()["result"]
net = pod.get("networking", {}).get("default", {})

print(f"=== {PG_POD_ID} networking ===")
print(f"  networking_live:  {pod.get('networking_live')}")
print(f"  url:              {net.get('url')}")
print(f"  protocol:         {net.get('protocol')}")
print(f"  port:             {net.get('port')}")
print(f"  cert_ready:       {net.get('cert_ready')}")
print(f"  cert_state:       {net.get('cert_state')}")
print(f"  cert_ready_at:    {net.get('cert_ready_at')}")

# API pod DATABASE_URL
r2 = requests.get(f"{BASE_URL}/v3/pods/{API_POD_ID}", headers=hdrs, timeout=30)
if not r2.ok:
    print(f"\nERROR fetching {API_POD_ID}: {r2.status_code}")
    sys.exit(1)

env = r2.json()["result"].get("environment_variables", {})
db_url = env.get("DATABASE_URL", "(not set)")
# Redact password
import re
db_url_safe = re.sub(r'(:)([^:@]+)(@)', r'\1***\3', db_url)
print(f"\n=== {API_POD_ID} DATABASE_URL ===")
print(f"  {db_url_safe}")
