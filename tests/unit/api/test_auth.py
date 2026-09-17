from dishka import make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.v1.dependencies.auth import require_api_key
from app.core.config import ConfigProvider, get_settings


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/secure", dependencies=[Depends(require_api_key)])
    async def secure() -> dict[str, str]:
        return {"ok": "yes"}

    setup_dishka(make_async_container(ConfigProvider(get_settings())), app)
    return app


def test_missing_api_key_is_401() -> None:
    client = TestClient(_app())
    response = client.get("/secure")
    assert response.status_code == 401


def test_wrong_api_key_is_401() -> None:
    client = TestClient(_app())
    response = client.get("/secure", headers={"X-API-Key": "nope"})
    assert response.status_code == 401


def test_valid_api_key_passes() -> None:
    client = TestClient(_app())
    response = client.get("/secure", headers={"X-API-Key": get_settings().api_key})
    assert response.status_code == 200
    assert response.json() == {"ok": "yes"}
