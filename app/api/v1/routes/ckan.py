import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies.auth import get_tapis_token_header
from app.services.ckan_service import CKANError, get_ckan_service

router = APIRouter(prefix="/ckan", tags=["ckan"])

logger = logging.getLogger(__name__)


@router.get("/organizations")
async def list_user_organizations(tapis_token: str = Depends(get_tapis_token_header)) -> List[Dict[str, Any]]:
    ckan_client = get_ckan_service()
    if not ckan_client:
        raise HTTPException(status_code=503, detail="CKAN integration is not configured.")

    try:
        return ckan_client.list_user_organizations(token=tapis_token)
    except CKANError as exc:
        logger.warning("CKAN organization lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to retrieve CKAN organizations.") from exc
