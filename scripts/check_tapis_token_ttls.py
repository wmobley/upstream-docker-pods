#!/usr/bin/env python3
"""
Empirically measure Tapis access-token and refresh-token TTLs for the current
tenant, to resolve Open Question #2 in
docs/design/2026-08-04-tapis-silent-token-refresh.md.

Logs in via tapipy (password grant), then decodes the exp/iat claims of both
the access token and the refresh token WITHOUT verifying signatures (same
approach tapipy itself uses internally) to compute each token's real TTL.
Never prints the raw token strings — only masked summaries and the computed
numbers.

Usage:
    export TAPIS_USERNAME=<your-tacc-username>
    export TAPIS_PASSWORD=<your-tacc-password>
    python3 scripts/check_tapis_token_ttls.py

Optional env vars (defaults shown):
    TAPIS_BASE_URL=https://portals.tapis.io
    TAPIS_TENANT_ID=portals
"""
import os
import sys
import datetime

import jwt
from tapipy.tapis import Tapis

BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
TENANT_ID = os.environ.get("TAPIS_TENANT_ID", "portals")


def masked(token_str: str) -> str:
    if not token_str:
        return "missing"
    return f"len={len(token_str)} prefix={token_str[:8]}... suffix=...{token_str[-8:]}"


def decode_claims(token_str: str) -> dict:
    # Signature verification intentionally skipped: we only need the exp/iat
    # claims to compute TTL, and we don't have (or need) the tenant's public
    # key cached here. Mirrors tapipy's own add_claims_to_token() approach.
    return jwt.decode(token_str, options={"verify_signature": False}, algorithms=["RS256"])


def describe(label: str, token_str: str) -> None:
    print(f"\n--- {label} ---")
    print(f"  token: {masked(token_str)}")
    try:
        claims = decode_claims(token_str)
    except Exception as exc:  # pragma: no cover - diagnostic script
        print(f"  ERROR decoding claims: {exc}")
        return

    iat = claims.get("iat")
    exp = claims.get("exp")
    if iat is None or exp is None:
        print(f"  claims missing iat/exp: keys present = {sorted(claims.keys())}")
        return

    ttl_seconds = exp - iat
    iat_dt = datetime.datetime.fromtimestamp(iat, tz=datetime.timezone.utc)
    exp_dt = datetime.datetime.fromtimestamp(exp, tz=datetime.timezone.utc)
    print(f"  issued_at:  {iat_dt.isoformat()}")
    print(f"  expires_at: {exp_dt.isoformat()}")
    print(f"  TTL:        {ttl_seconds} seconds  (~{ttl_seconds / 3600:.2f} hours, ~{ttl_seconds / 86400:.2f} days)")


def main() -> int:
    username = os.environ.get("TAPIS_USERNAME")
    password = os.environ.get("TAPIS_PASSWORD")
    if not username or not password:
        print("ERROR: set TAPIS_USERNAME and TAPIS_PASSWORD environment variables first.")
        print("These should be your own TACC/Tapis credentials - do not hardcode them here.")
        return 1

    print(f"Authenticating as {username} to {BASE_URL} (tenant={TENANT_ID}) ...")
    t = Tapis(base_url=BASE_URL, tenant_id=TENANT_ID, username=username, password=password)
    t.get_tokens()
    print("Login succeeded.\n")

    access_token_str = t.access_token.access_token
    describe("Access token", access_token_str)

    if getattr(t, "refresh_token", None):
        refresh_token_str = t.refresh_token.refresh_token
        describe("Refresh token", refresh_token_str)
    else:
        print("\n--- Refresh token ---")
        print("  No refresh token was returned for this grant/tenant configuration.")
        print("  This itself answers part of Open Question #5: refresh tokens are not")
        print("  guaranteed for every Tapis auth path.")

    print("\nDone. Report the two TTL numbers above (not the raw tokens) back for the design spec.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
