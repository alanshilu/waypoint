# app/api/v1/tracking.py (FastAPI)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

@router.websocket("/ws/live-location")
async def live_location_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Receive the JSON payload from the frontend
            data = await websocket.receive_json()
            
            lat = data.get("lat")
            lon = data.get("lon")
            
            # Here you could save the point to your database, 
            # recalculate the route if they go off-path, 
            # or broadcast the location to another user.
            print(f"User on Trip is at {lat}, {lon}")
            
    except WebSocketDisconnect:
        print(f"Trip disconnected.")