#!/usr/bin/env python3
"""
Create the upstream-develop and upstream-developapi pods on portals.develop.tapis.io.

Usage:
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>
    export PG_PASSWORD=<choose-a-postgres-password>
    python3 scripts/create_develop_pods.py

Optional env vars (defaults shown):
    TAPIS_BASE_URL=https://portals.develop.tapis.io
    PG_USER=pguser
    API_IMAGE=ghcr.io/wmobley/upstream-docker-pods:feature-unified-ui-tapis-auth
    UI_IMAGE=ghcr.io/wmobley/upstream-ui-pods:feature-unified-ui-tapis-auth
"""
import os
import sys
import requests
from tapipy.tapis import Tapis

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
PODS_DOMAIN = BASE_URL.replace("https://", "pods.")

USERNAME = os.environ["TAPIS_USERNAME"]
PASSWORD = os.environ["TAPIS_PASSWORD"]
PG_USER = os.environ.get("PG_USER", "pguser")
PG_PASSWORD = os.environ["PG_PASSWORD"]

API_IMAGE = os.environ.get(
    "API_IMAGE",
    "ghcr.io/wmobley/upstream-docker-pods:feature-unified-ui-tapis-auth",
)
UI_IMAGE = os.environ.get(
    "UI_IMAGE",
    "ghcr.io/wmobley/upstream-ui-pods:feature-unified-ui-tapis-auth",
)

VOLUME_ID     = "upstreamdevelopvolume"
POSTGRES_ID   = "upstreamdeveloppostgres"
API_ID        = "upstreamdevelopapi"
UI_ID         = "upstreamdevelop"

ADMIN_USERS = ["wmobley", "tasclient_dsso"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
print(f"Authenticating as {USERNAME} to {BASE_URL} …")
t = Tapis(base_url=BASE_URL, username=USERNAME, password=PASSWORD)
t.get_tokens()
token = t.access_token.access_token
print("Token acquired.")

headers = {
    "X-Tapis-Token": token,
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def pods_post(path: str, payload: dict) -> dict:
    url = f"{BASE_URL}/v3{path}"
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"POST {path} → {r.status_code}: {r.text}")
    return r.json()


def pods_put(path: str, payload: dict) -> dict:
    url = f"{BASE_URL}/v3{path}"
    r = requests.put(url, headers=headers, json=payload, timeout=30)
    if not r.ok:
        raise RuntimeError(f"PUT {path} → {r.status_code}: {r.text}")
    return r.json()


# ---------------------------------------------------------------------------
# Show allowed images (helpful for debugging allowlist issues)
# ---------------------------------------------------------------------------
print("\nFetching allowed images …")
images_resp = requests.get(f"{BASE_URL}/v3/pods/images", headers=headers, timeout=30)
if images_resp.ok:
    images = images_resp.json().get("result", [])
    for img in images:
        image_val = img if isinstance(img, str) else img.get("image_id") or img.get("name") or str(img)
        print(f"  {image_val}")
else:
    print(f"  (could not fetch: {images_resp.status_code})")

# ---------------------------------------------------------------------------
# Stack (must exist before pods can reference it)
# ---------------------------------------------------------------------------
STACK_ID = "upstreamdevelop"
print(f"Creating stack {STACK_ID} …")
try:
    pods_post("/pods/stacks", {"stack_id": STACK_ID, "description": "Upstream develop"})
    print("  Created.")
except RuntimeError as e:
    msg = str(e).lower()
    if "already exists" in msg or "uniqueviolation" in msg:
        print("  Already exists — skipping.")
    elif "responsevalidationerror" in msg:
        # Tapis Pods server bug: stack created OK but response serialization fails.
        print("  Created (server returned 500 ResponseValidationError — stack exists).")
    else:
        raise

# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------
print(f"\nCreating volume {VOLUME_ID} …")
try:
    pods_post("/pods/volumes", {"volume_id": VOLUME_ID, "description": "Postgres data for upstream-develop"})
    print("  Created.")
except RuntimeError as e:
    if "already exists" in str(e).lower() or "uniqueviolation" in str(e).lower():
        print("  Already exists — skipping.")
    else:
        raise

# ---------------------------------------------------------------------------
# Postgres pod
# ---------------------------------------------------------------------------
print(f"Creating pod {POSTGRES_ID} …")
postgres_payload = {
    "pod_id": POSTGRES_ID,
    "image": "postgis/postgis:17-3.5",
    "description": "Postgres for upstream-develop",
    "environment_variables": {
        "POSTGRES_USER": PG_USER,
        "POSTGRES_PASSWORD": PG_PASSWORD,
        "POSTGRES_DB": PG_USER,
    },
    "status_requested": "ON",
    "volume_mounts": {
        "/var/lib/postgresql/data": {
            "type": "tapisvolume",
            "source_id": VOLUME_ID,
            "sub_path": "",
        }
    },
    "time_to_stop_default": -1,
    "networking": {
        "default": {
            "protocol": "postgres",
            "port": 5432,
            "url": f"{POSTGRES_ID}.{PODS_DOMAIN}",
        }
    },
    "resources": {"cpu_request": 250, "cpu_limit": 2000, "mem_request": 256, "mem_limit": 3072, "gpus": 0},
}
try:
    pods_post("/pods", postgres_payload)
    print("  Created.")
except RuntimeError as e:
    if "already exists" in str(e).lower() or "uniqueviolation" in str(e).lower():
        print("  Already exists — skipping.")
    else:
        raise

# ---------------------------------------------------------------------------
# API pod
# ---------------------------------------------------------------------------
print(f"Creating pod {API_ID} …")
api_payload = {
    "pod_id": API_ID,
    "image": API_IMAGE,
    "description": "Upstream develop API",
    "stack_id": STACK_ID,
    "command": ["/bin/bash", "-c", "until alembic upgrade heads; do echo 'DB not ready, retrying in 10s...'; sleep 10; done && uvicorn app.main:app --reload --host 0.0.0.0"],
    "environment_variables": {
        "DATABASE_URL": f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{POSTGRES_ID}.{PODS_DOMAIN}:443/{PG_USER}",
        "POSTGRES_PASSWORD": PG_PASSWORD,
        "TAS_USER": os.environ.get("TAS_USER", USERNAME),
        "TAS_SECRET": os.environ.get("TAS_SECRET", PASSWORD),
        "JWT_SECRET": os.environ.get("JWT_SECRET", "changeme-dev-secret"),
        "ALG": "HS256",
        "TAS_URL": BASE_URL,
        "ENVIRONMENT": "develop",
        "ENV": "develop",
        "CKAN_URL": os.environ.get("CKAN_URL", ""),
        "CKAN_TIMEOUT": "30",
        "CKAN_ORGANIZATION": "upstream",
        "CKAN_ADMIN_USERNAME": "dso_test",
        "CKAN_ADMIN_API_KEY": os.environ.get("CKAN_ADMIN_API_KEY", ""),
        "UI_BASE_URL": f"https://{UI_ID}.{PODS_DOMAIN}",
        "API_BASE_URL": f"https://{API_ID}.{PODS_DOMAIN}",
        "TAPIS_BASE_URL": "https://portals.tapis.io",
        "TAPIS_TENANT_ID": "portals",
    },
    "status_requested": "ON",
    "volume_mounts": {},
    "time_to_stop_default": -1,
    "networking": {
        "default": {
            "protocol": "http",
            "port": 8000,
            "url": f"{API_ID}.{PODS_DOMAIN}",
        }
    },
    "resources": {"cpu_request": 250, "cpu_limit": 2000, "mem_request": 256, "mem_limit": 3072, "gpus": 0},
}
try:
    pods_post("/pods", api_payload)
    print("  Created.")
except RuntimeError as e:
    if "already exists" in str(e).lower() or "uniqueviolation" in str(e).lower():
        print("  Already exists — skipping.")
    else:
        raise

# ---------------------------------------------------------------------------
# UI pod (unified, shared)
# ---------------------------------------------------------------------------
print(f"Creating pod {UI_ID} …")
ui_payload = {
    "pod_id": UI_ID,
    "image": UI_IMAGE,
    "description": "Upstream unified UI (develop)",
    "environment_variables": {
        "VITE_TAPIS_PODS_BASE_URL": BASE_URL,
    },
    "status_requested": "ON",
    "volume_mounts": {},
    "time_to_stop_default": -1,
    "networking": {
        "default": {
            "protocol": "http",
            "port": 80,
            "url": f"{UI_ID}.{PODS_DOMAIN}",
        }
    },
    "resources": {"cpu_request": 250, "cpu_limit": 500, "mem_request": 256, "mem_limit": 512, "gpus": 0},
}
try:
    pods_post("/pods", ui_payload)
    print("  Created.")
except RuntimeError as e:
    if "already exists" in str(e).lower() or "uniqueviolation" in str(e).lower():
        print("  Already exists — skipping.")
    else:
        raise

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
print("\nGranting admin permissions …")
for user in ADMIN_USERS:
    for pod_id in [POSTGRES_ID, API_ID, UI_ID]:
        try:
            pods_post(f"/pods/{pod_id}/permissions", {"user": user, "level": "ADMIN"})
            print(f"  {pod_id}: {user} → ADMIN")
        except RuntimeError:
            print(f"  {pod_id}: {user} → (already set or skipped)")

    try:
        pods_post(f"/pods/volumes/{VOLUME_ID}/permissions", {"user": user, "level": "ADMIN"})
        print(f"  {VOLUME_ID}: {user} → ADMIN")
    except RuntimeError:
        print(f"  {VOLUME_ID}: {user} → (already set or skipped)")

print("\nDone! Pod URLs:")
print(f"  UI  → https://{UI_ID}.{PODS_DOMAIN}")
print(f"  API → https://{API_ID}.{PODS_DOMAIN}")
print(f"  DB  → {POSTGRES_ID}.{PODS_DOMAIN}:443")
print("\nNote: pods take a few minutes to reach RUNNING state.")
print("Check status at: " + BASE_URL + "/v3/pods")
