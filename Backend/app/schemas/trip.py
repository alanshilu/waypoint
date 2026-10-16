from pydantic import BaseModel


class TripCreate(BaseModel):
	name: str | None = None
	origin_name: str
	origin_lat: float
	origin_lon: float
	destination_name: str
	destination_lat: float
	destination_lon: float
