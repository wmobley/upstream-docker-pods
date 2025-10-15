from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.main import api_router


app = FastAPI(
    title="Upstream Sensor Storage",
    description="Sensor Storage for Upstream data",
    version="0.0.1",
    contact={
        "name": "Will Mobley",
        "email": "wmobley@tacc.utexas.edu",
    },

)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(api_router, prefix="/api/v1")