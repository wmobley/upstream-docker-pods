#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Ensure the repo root is on sys.path so this helper can be executed from any cwd.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests

from app.services.ckan_service import CKANError, CKANService

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Debug CKAN bearer-token / X-Tapis-Token auth against a CKAN instance"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CKAN_URL"),
        help="CKAN base URL, e.g. https://ckan.tacc.utexas.edu",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CKAN_TOKEN"),
        help="Bearer or X-Tapis token to use for authentication",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("CKAN_USERNAME"),
        help="CKAN username to validate membership for",
    )
    parser.add_argument(
        "--organization",
        default=os.environ.get("CKAN_ORGANIZATION"),
        help="CKAN organization id/name to validate membership against",
    )
    parser.add_argument(
        "--dataset-id",
        default=os.environ.get("CKAN_DATASET_ID"),
        help="Optional dataset id/name for package_show validation",
    )
    parser.add_argument(
        "--auth-mode",
        choices=["combined", "bearer", "x_tapis", "all"],
        default="all",
        help="Auth mode to test when listing user organizations",
    )
    parser.add_argument(
        "--raw-user-show",
        action="store_true",
        help="Run /api/3/action/user_show?id=<username> with Authorization: Bearer <token>",
    )
    parser.add_argument(
        "--test-write",
        action="store_true",
        help="Test CKAN package_create/package_patch authorization using an existing dataset ID",
    )
    parser.add_argument(
        "--log-file",
        help="Optional path to write debug output to a file",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def error(message: str) -> None:
    logger.error(message)
    sys.exit(1)


def setup_logging(log_file: str | None, debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(level)


def print_json(value: Any) -> None:
    text = json.dumps(value, indent=2, sort_keys=True)
    logger.info("\n%s", text)


def make_ckan_client(base_url: str) -> CKANService:
    client = CKANService(base_url=base_url, timeout=30)
    return client


def request_user_show(base_url: str, token: str, username: str) -> Any:
    url = f"{base_url.rstrip('/')}/api/3/action/user_show"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.get(url, headers=headers, params={"id": username}, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError:
        raise CKANError(f"user_show request failed {response.status_code}: {response.text}")
    payload = response.json()
    if not payload.get("success", False):
        raise CKANError(str(payload.get("error", payload)))
    return payload["result"]


def test_ckan_dataset_write(
    ckan_client: CKANService,
    token: str,
    dataset_id: str,
    owner_org: str | None,
) -> dict[str, Any]:
    dataset = ckan_client.get_dataset(token=token, name_or_id=dataset_id)
    dataset_name = dataset.get("name")
    if not dataset_name:
        raise CKANError("Dataset returned from CKAN has no name")

    tags: list[str] = []
    for tag_obj in dataset.get("tags", []):
        if isinstance(tag_obj, dict) and isinstance(tag_obj.get("name"), str):
            tags.append(tag_obj["name"])

    extras = [
        extra
        for extra in dataset.get("extras", [])
        if isinstance(extra, dict) and "key" in extra and "value" in extra
    ]

    title = dataset.get("title") or dataset_name
    notes = dataset.get("notes") or ""
    private = bool(dataset.get("private", True))
    owner_org_value = owner_org or dataset.get("owner_org")

    if not owner_org_value:
        raise CKANError(
            "Cannot run write test: dataset owner_org is missing and no --organization was provided"
        )

    logger.info("Running CKAN write test against dataset %s", dataset_id)
    return ckan_client.create_or_update_dataset(
        token=token,
        name=dataset_name,
        title=title,
        owner_org=owner_org_value,
        notes=notes,
        tags=tags,
        extras=extras,
        private=private,
        extra_fields={},
    )


def main() -> int:
    args = parse_args()
    setup_logging(args.log_file, args.debug)

    if not args.base_url:
        error("CKAN base URL is required via --base-url or CKAN_URL environment variable.")
    if not args.token:
        error("Authentication token is required via --token or CKAN_TOKEN environment variable.")

    client = make_ckan_client(args.base_url)
    modes = [args.auth_mode] if args.auth_mode != "all" else ["combined", "bearer", "x_tapis"]

    results: dict[str, Any] = {}
    for mode in modes:
        try:
            logger.info("Listing organizations with auth_mode=%s", mode)
            organizations = client.list_user_organizations(token=args.token, auth_mode=mode)
            results[mode] = {
                "success": True,
                "organization_count": len(organizations),
                "organizations": organizations,
            }
        except CKANError as exc:
            results[mode] = {
                "success": False,
                "error": str(exc),
            }

    print_json({"organization_lookup": results})

    if args.organization:
        org_result = {
            "organization": args.organization,
            "user_membership": {},
        }
        for mode in modes:
            try:
                member = client.user_is_in_organization(
                    token=args.token,
                    organization_id=args.organization,
                    username=args.username or "",
                    auth_mode=mode,
                )
                org_result["user_membership"][mode] = {
                    "success": True,
                    "is_member": member,
                }
            except CKANError as exc:
                org_result["user_membership"][mode] = {
                    "success": False,
                    "error": str(exc),
                }
        print_json({"organization_membership": org_result})

    if args.dataset_id:
        try:
            logger.info("Fetching dataset %s", args.dataset_id)
            dataset = client.get_dataset(token=args.token, name_or_id=args.dataset_id)
            print_json({"dataset": dataset})
        except CKANError as exc:
            logger.error("Dataset lookup failed: %s", exc)

    if args.test_write:
        if not args.dataset_id:
            error("--test-write requires --dataset-id to be provided.")
        try:
            result = test_ckan_dataset_write(
                ckan_client=client,
                token=args.token,
                dataset_id=args.dataset_id,
                owner_org=args.organization,
            )
            print_json({"write_test_result": result})
        except CKANError as exc:
            logger.error("CKAN write auth test failed: %s", exc)
            return 1

    if args.raw_user_show:
        if not args.username:
            error("--raw-user-show requires --username to be provided.")
        try:
            user = request_user_show(args.base_url, args.token, args.username)
            print_json({"user_show": user})
        except CKANError as exc:
            logger.error("user_show failed: %s", exc)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
