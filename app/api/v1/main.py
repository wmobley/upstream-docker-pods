from fastapi import APIRouter

from app.api.v1.routes.campaigns.campaign_station_sensors import (
    router as campaign_station_sensors_router,
)
from app.api.v1.routes.campaigns.campaign_station_sensor_measurements import (
    router as campaign_station_sensor_measurements_router,
)
from app.api.v1.routes.campaigns.campaign_stations import (
    router as stations_router,
)
from app.api.v1.routes.sensor_variables.sensor_variables import (
    router as sensor_variables_router,
)
from app.api.v1.routes.campaigns.root import router as campaigns_router
from app.api.v1.routes.root import router as root_router
from app.api.v1.routes.upload_file.upload_csv import router as upload_file_csv_router # type: ignore[attr-defined]
from app.api.v1.routes.projects.projects import router as projects_router
from app.api.v1.routes.ckan import router as ckan_router
from app.api.v1.routes.pods import router as pods_router
from app.api.v1.routes.user_roles import router as user_roles_router

api_router = APIRouter()
api_router.include_router(root_router)
api_router.include_router(campaigns_router)
api_router.include_router(stations_router)
api_router.include_router(campaign_station_sensors_router)
api_router.include_router(campaign_station_sensor_measurements_router)
api_router.include_router(sensor_variables_router)
api_router.include_router(upload_file_csv_router)
api_router.include_router(projects_router)
api_router.include_router(ckan_router)
api_router.include_router(pods_router)
api_router.include_router(user_roles_router)
