from app.pytas.http import TASClient # type: ignore[attr-defined]
from app.pytas.models.schemas import PyTASUser, PyTASProject
from app.core.config import get_settings

from typing import List
settings = get_settings()

class ProjectService:
    def __init__(self) -> None:
        self.client = TASClient(
            baseURL=settings.TAS_URL,
            credentials={
                "username": settings.TAS_USER,
                "password": settings.TAS_SECRET,
            },
        )

    def get_projects_for_user(self, username: str) -> List[PyTASProject]:
        active_projects = []
        for p in self.client.projects_for_user(username=username):
            if p.allocations[0].status != "Inactive":
                active_projects.append(p)
        return active_projects


    def get_project_members(self, project_id: str) -> List[PyTASUser]:
        return self.client.get_project_members(project_id=project_id)  # type: ignore[no-any-return]
