from fastapi import APIRouter, Depends

from app.api.dependencies.auth import get_current_user
from app.api.v1.schemas.user import User
from app.services.project_service import ProjectService
from app.pytas.models.schemas import PyTASProject, PyTASUser
router = APIRouter(prefix="", tags=["projects"])

@router.get("/projects")
async def get_projects(current_user: User = Depends(get_current_user)) -> list[PyTASProject]:
    return ProjectService().get_projects_for_user(current_user.username)


@router.get("/projects/{project_id}/members")
async def get_project_members_for_user(project_id: str) -> list[PyTASUser]:
    return ProjectService().get_project_members(project_id)