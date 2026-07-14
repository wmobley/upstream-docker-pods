#!/usr/bin/env python3
"""
Update the CORS settings on the upstreamdevelopapi pod's networking config.
Builds the networking payload from known-writable fields only (avoids
sending read-only computed fields back to Tapis which causes 400 errors).

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    python3 scripts/update_cors.py

Optional env vars:
    TAPIS_BASE_URL=https://portals.tapis.io
    API_POD_ID=upstreamdevelopapi
    CORS_ORIGIN=https://upstreamdevelop.pods.portals.tapis.io
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
PODS_DOMAIN = BASE_URL.replace("https://", "pods.")
API_POD_ID = os.environ.get("API_POD_ID", "upstreamdevelopapi")
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://upstreamdevelop.pods.portals.tapis.io")

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

# Fetch current pod to get protocol/port/url (read them, don't echo back the
# full object which includes read-only computed cert_* fields).
r = requests.get(f"{BASE_URL}/v3/pods/{API_POD_ID}", headers=headers, timeout=30)
if not r.ok:
    print(f"ERROR fetching pod: {r.status_code}: {r.text}")
    sys.exit(1)

pod = r.json()["result"]
net = pod.get("networking", {}).get("default", {})
protocol = net.get("protocol", "http")
port = net.get("port", 8000)
url = net.get("url", f"{API_POD_ID}.{PODS_DOMAIN}")

# Build networking payload with only writable fields.
# Values mirror the working production upstreamapi pod.
networking_payload = {
    "default": {
        "protocol": protocol,
        "port": port,
        "url": url,
        "cors_allow_origins": [CORS_ORIGIN],
        "cors_allow_methods": ["GET", "POST", "OPTIONS", "DELETE", "PUT", "HEAD", "PATCH"],
        "cors_allow_headers": [
            "content-type",
            "authorization",
            "x-tapis-token",
            "x-tapis-tenant",
            "x-tapis-username",
            "x-tapis-site",
        ],
        "cors_allow_credentials": False,
    }
}

print(f"Setting CORS on {API_POD_ID}:")
print(f"  cors_allow_origins:  [{CORS_ORIGIN}]")
print(f"  cors_allow_methods:  GET POST OPTIONS DELETE PUT HEAD PATCH")
print(f"  cors_allow_headers:  content-type, x-tapis-token, authorization")
print(f"  cors_allow_credentials: false")
print()

payload = {
    "networking": networking_payload,
    "status_requested": "RESTART",
}

r = requests.put(f"{BASE_URL}/v3/pods/{API_POD_ID}", headers=headers, json=payload, timeout=30)
if not r.ok:
    print(f"ERROR updating pod: {r.status_code}: {r.text}")
    sys.exit(1)

print(f"Pod {API_POD_ID} updated and restarting.")
print(f"Check status: {BASE_URL}/v3/pods/{API_POD_ID}")
