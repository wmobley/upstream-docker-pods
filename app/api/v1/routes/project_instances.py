import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.dependencies.auth import get_current_user
from app.api.v1.schemas.user import User
from app.services.project_discovery import discover_project_instances

router = APIRouter(prefix="/project-instances", tags=["project-instances"])
logger = logging.getLogger(__name__)


@router.get("")
def list_project_instances(
    _user: User = Depends(get_current_user),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> list[dict[str, str]]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer Tapis token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tapis_token = authorization.split(" ", 1)[1].strip()
    if not tapis_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer Tapis token required")
    try:
        instances = discover_project_instances(tapis_token)
        logger.info("project_instances_discovery_succeeded extra=%s", {"instance_count": len(instances)})
        return instances
    except Exception as exc:
        logger.exception(
            "project_instances_discovery_failed extra=%s",
            {"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Project discovery service unavailable",
        ) from exc
