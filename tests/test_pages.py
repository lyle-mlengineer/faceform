from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        jwt_secret="test-secret-that-is-long-enough-for-local-tests",
        firebase_web_api_key="test-key",
        firebase_web_auth_domain="faceform.firebaseapp.com",
        firebase_web_project_id="faceform",
        firebase_web_app_id="test-app",
    )
    with TestClient(create_app(settings, database_url="sqlite:///:memory:")) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("path", "expected_text"),
    [
        ("/", "Photoreal faces for every post"),
        ("/product", "Your creative brief"),
        ("/login", "Welcome back."),
        ("/register", "Create your account."),
        ("/dashboard", "Your recent faces"),
        ("/gallery", "Your albums"),
        ("/billing", "Credit packs"),
    ],
)
def test_frontend_pages_render(client: TestClient, path: str, expected_text: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert expected_text in response.text
    assert "/static/css/site.css" in response.text


def test_static_assets_and_firebase_client_config(client: TestClient) -> None:
    css = client.get("/static/css/site.css")
    script = client.get("/static/js/app.js")
    auth_page = client.get("/register")

    assert css.status_code == 200
    assert "prefers-reduced-motion" in css.text
    assert script.status_code == 200
    assert "mountStudio" in script.text
    assert '"apiKey": "test-key"' in auth_page.text
