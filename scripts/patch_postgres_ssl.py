#!/usr/bin/env python3
"""
Switch upstreamdeveloppostgres to the Tapis pod_template and enable SSL,
then restart it. Data is on a persistent volume so no data is lost.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/patch_postgres_ssl.py
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

payload = {
    "command": ["docker-entrypoint.sh"],
    "arguments": [
        "-c", "ssl=on",
        "-c", "ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem",
        "-c", "ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key",
    ],
    "status_requested": "RESTART",
}

print(f"Patching {PG_POD_ID}: enabling postgres SSL with snakeoil certs ...")
r = requests.put(f"{BASE_URL}/v3/pods/{PG_POD_ID}", headers=hdrs, json=payload, timeout=30)
if not r.ok:
    print(f"ERROR: {r.status_code}: {r.text}")
    sys.exit(1)

print(f"Done — {PG_POD_ID} restarting with SSL.")
print(f"Wait ~3 min, then: python3 scripts/check_pod_status.py")
