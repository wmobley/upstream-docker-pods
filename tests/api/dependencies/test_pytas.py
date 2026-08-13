from typing import Literal

import pytest
from fastapi import HTTPException

from app.api.dependencies import ckan as pytas
from app.api.v1.schemas.user import User

CampaignAllocationRow = tuple[str | None] | None


class FakeQuery:
    def __init__(self, row: CampaignAllocationRow) -> None:
        self.row = row
        self.filters: list[object] = []

    def filter(self, *criteria: object) -> "FakeQuery":
        self.filters.extend(criteria)
        return self

    def first(self) -> CampaignAllocationRow:
        return self.row


class FakeSession:
    def __init__(self, row: CampaignAllocationRow) -> None:
        self.query_obj = FakeQuery(row)
        self.query_called = False

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *_exc: object) -> Literal[False]:
        return False

    def query(self, *_columns: object) -> FakeQuery:
        self.query_called = True
        return self.query_obj


def make_user() -> User:
    return User(username="alice", role="READ")


def patch_session(monkeypatch: pytest.MonkeyPatch, row: CampaignAllocationRow) -> FakeSession:
    session = FakeSession(row)
    monkeypatch.setattr(pytas, "SessionLocal", lambda: session)
    return session


def test_check_allocation_permission_normalizes_campaign_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_session(monkeypatch, (" DSO-Institute ",))

    assert pytas.check_allocation_permission(
        make_user(), campaign_id=5, allocations=["dso-institute"]
    ) is True


def test_check_allocation_permission_denies_unrelated_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_session(monkeypatch, ("dso-institute",))

    with pytest.raises(HTTPException) as exc_info:
        pytas.check_allocation_permission(
            make_user(), campaign_id=5, allocations=["other-org"]
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Access to Campaign unavailable. Improper Allocation"


def test_check_allocation_permission_denies_blank_campaign_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_session(monkeypatch, (" ",))

    with pytest.raises(HTTPException):
        pytas.check_allocation_permission(
            make_user(), campaign_id=5, allocations=["dso-institute"]
        )


def test_check_allocation_permission_allows_empty_allocations_without_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = patch_session(monkeypatch, ("dso-institute",))

    assert pytas.check_allocation_permission(
        make_user(), campaign_id=5, allocations=[]
    ) is True
    assert session.query_called is False
