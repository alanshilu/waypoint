# app/main.py
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.endpoints import agent, health, location, pois, routes, trips, weather
from app.core.config import settings

app = FastAPI()

# Browser origins come from settings (CORS_ORIGINS): the Vite dev server and the deployed frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_errors(request: Request, exc: RequestValidationError):
    """The agent endpoints use one error shape; other endpoints keep FastAPI's default."""
    if request.url.path.startswith("/agent"):
        message = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": message}})
    return await request_validation_exception_handler(request, exc)


# This registers your endpoints under specific prefixes
app.include_router(weather.router, prefix="/weather", tags=["Weather"])
app.include_router(location.router, prefix="/location", tags=["Location"])
app.include_router(pois.router, prefix="/pois", tags=["POIs"])
app.include_router(trips.router, prefix="/trips", tags=["Trips"])
app.include_router(routes.router, prefix="/routes", tags=["Routes"])
app.include_router(agent.router, prefix="/agent", tags=["Agent"])
app.include_router(health.router, prefix="/health", tags=["Health"])