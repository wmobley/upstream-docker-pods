from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_current_user
from app.api.v1.schemas.user import User
from app.db.repositories.sensor_repository import SensorRepository
from app.db.session import get_db

router = APIRouter(prefix="/sensor_variables", tags=["sensor_variables"])


@router.get("")
async def list_sensor_variables(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[str]:
    sensor_repository = SensorRepository(db)
    return sensor_repository.list_sensor_variables()

