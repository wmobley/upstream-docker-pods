from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies.auth import get_edit_user
from app.api.v1.schemas.user import User
from app.services.pods_service import PodsService
from typing import Dict, Any

router = APIRouter(prefix="/pods", tags=["pods"])


class BundleRequest(BaseModel):
    base: str = Field(..., description="Base name for the pod bundle (e.g., sniffer)")
    pg_user: str = Field(..., description="Postgres username")
    pg_password: str = Field(..., description="Postgres password")


@router.post("/bundle", status_code=status.HTTP_201_CREATED)
def create_pod_bundle(payload: BundleRequest, _user: User = Depends(get_edit_user)) -> Dict[str, Any]:
    """
    Create a Postgres/API/UI pod bundle using server-side credentials.
    """
    service = PodsService()
    try:
        created = service.build_bundle(
            base=payload.base,
            pg_user=payload.pg_user,
            pg_password=payload.pg_password,
        )
        return {"status": "requested", "created": created}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
