import pytest

from app.api.v1.endpoints import agent as agent_api
from app.main import app


class RecordingPlanStore:
    """Keeps saved plans in memory, so agent tests never reach a database."""

    def __init__(self):
        self.saved: list[tuple[int, dict]] = []

    def save(self, trip_id: int, snapshot: dict) -> None:
        self.saved.append((trip_id, snapshot))


@pytest.fixture(autouse=True)
def plan_store():
    store = RecordingPlanStore()
    app.dependency_overrides[agent_api.get_plan_store] = lambda: store
    yield store
    app.dependency_overrides.pop(agent_api.get_plan_store, None)
