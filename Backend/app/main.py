# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import location, pois, weather, trips,routes
app = FastAPI()

# Allow the Vite dev server (Frontend/) to call the API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# This registers your endpoints under specific prefixes
app.include_router(weather.router, prefix="/weather", tags=["Weather"])
app.include_router(location.router, prefix="/location", tags=["Location"])
app.include_router(pois.router, prefix="/pois", tags=["POIs"])
app.include_router(trips.router, prefix="/trips", tags=["Trips"])
app.include_router(routes.router, prefix="/routes", tags=["Routes"])