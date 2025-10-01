from typing import Any, List, Optional

from pydantic import BaseModel


class PyTASUser(BaseModel):
    id: int
    username: str
    role: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None


class PyTASPi(BaseModel):
    id: int
    username: str
    email: str
    firstName: str
    lastName: str
    institution: str
    institutionId: int
    department: str
    departmentId: int
    citizenship: str
    citizenshipId: int
    source: str
    uid: int
    homeDirectory: str
    gid: int


class PyTASAllocation(BaseModel):
    id: int
    start: str
    end: str
    status: str
    justification: str
    decisionSummary: Optional[str]
    dateRequested: str
    dateReviewed: Optional[str]
    computeRequested: int
    computeAllocated: int
    storageRequested: int
    storageAllocated: int
    memoryRequested: int
    memoryAllocated: int
    resourceId: int
    resource: str
    projectId: int
    project: str
    requestorId: int
    requestor: str
    reviewerId: int
    reviewer: Any
    computeUsed: float


class PyTASProject(BaseModel):
    id: int
    title: str
    description: str
    chargeCode: str
    gid: int
    source: Any
    fieldId: int
    field: str
    typeId: int
    type: str
    piId: int
    pi: PyTASPi
    allocations: List[PyTASAllocation]
    nickname: Any
