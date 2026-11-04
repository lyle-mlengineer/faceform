from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import ProviderRequestError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    async def fake_generate_images(settings: Settings, prompt: str, count: int) -> list[str]:
        return [f"https://images.example.test/{index}.png" for index in range(count)]

    monkeypatch.setattr("app.api.generate_images", fake_generate_images)
    settings = Settings(
        _env_file=None,
        jwt_secret="test-secret-that-is-long-enough-for-local-tests",
        mpesa_consumer_key="consumer",
        mpesa_consumer_secret="secret",
        mpesa_shortcode="123456",
        mpesa_passkey="passkey",
        mpesa_callback_url="https://api.example.test/api/v1/billing/mpesa/callback",
        payment_webhook_secret="webhook-secret",
    )
    application = create_app(settings, database_url="sqlite:///:memory:")
    with TestClient(application) as test_client:
        yield test_client


def register(client: TestClient, email: str = "person@example.com") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "FaceForm User", "password": "secure-test-password"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_guest_can_generate_once_and_claim_generation(client: TestClient) -> None:
    request = {
        "title": "Summer campaign",
        "gender": "woman",
        "age_range": "25-34",
        "ethnicity": "East African",
        "description": "Warm smile, curly hair, small gold earrings, studio portrait.",
        "number_of_images": 1,
    }
    generated = client.post("/api/v1/generations", json=request)
    assert generated.status_code == 201, generated.text
    data = generated.json()
    assert data["generation"]["status"] == "completed"
    assert len(data["generation"]["images"]) == 1
    assert data["guest_token"]

    repeated = client.post(
        "/api/v1/generations",
        json=request,
        headers={"X-Guest-Token": data["guest_token"]},
    )
    assert repeated.status_code == 409

    authenticated = client.post(
        "/api/v1/auth/register",
        json={
            "email": "guest@example.com",
            "name": "Guest",
            "password": "secure-test-password",
            "guest_token": data["guest_token"],
        },
    )
    assert authenticated.status_code == 201, authenticated.text
    assert authenticated.json()["claimed_generations"] == 1
    headers = {"Authorization": f"Bearer {authenticated.json()['access_token']}"}

    gallery = client.get("/api/v1/gallery", headers=headers)
    assert gallery.status_code == 200
    assert gallery.json()[0]["id"] == data["generation"]["images"][0]["id"]
    download = client.get(
        f"/api/v1/images/{gallery.json()[0]['id']}/download",
        headers=headers,
        follow_redirects=False,
    )
    assert download.status_code == 307
    assert download.headers["location"] == "https://images.example.test/0.png"


def test_manual_mpesa_payment_is_idempotent_and_generation_debits_credits(client: TestClient) -> None:
    account = register(client)
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    insufficient = client.post(
        "/api/v1/generations",
        headers=headers,
        json={
            "title": "Portrait",
            "gender": "woman",
            "age_range": "25-34",
            "ethnicity": "East African",
            "description": "Natural portrait lighting and a friendly expression.",
        },
    )
    assert insufficient.status_code == 402

    created = client.post(
        "/api/v1/billing/payments",
        headers=headers,
        json={"pack_code": "starter", "method": "mpesa_till"},
    )
    assert created.status_code == 201, created.text
    details = created.json()
    assert details["instructions"]["business_number"] == "123456"
    reference = details["instructions"]["account_reference"]

    callback = {
        "payment_reference": reference,
        "receipt_number": "QAB123456",
        "amount_kes": 500,
    }
    settled = client.post(
        "/api/v1/billing/manual/callback",
        json=callback,
        headers={"X-Payment-Webhook-Secret": "webhook-secret"},
    )
    assert settled.status_code == 200, settled.text
    repeated = client.post(
        "/api/v1/billing/manual/callback",
        json=callback,
        headers={"X-Payment-Webhook-Secret": "webhook-secret"},
    )
    assert repeated.status_code == 200
    dashboard = client.get("/api/v1/dashboard", headers=headers)
    assert dashboard.json()["credits"] == 60

    generated = client.post(
        "/api/v1/generations",
        headers=headers,
        json={
            "title": "Product portrait",
            "gender": "man",
            "age_range": "30-39",
            "ethnicity": "East African",
            "description": "Short hair, brown eyes, wearing simple glasses.",
            "number_of_images": 1,
        },
    )
    assert generated.status_code == 201, generated.text
    assert generated.json()["credits_charged"] == 6
    assert client.get("/api/v1/dashboard", headers=headers).json()["credits"] == 54
    generation_id = generated.json()["generation"]["id"]

    updated = client.patch(
        f"/api/v1/generations/{generation_id}",
        headers=headers,
        json={"description": "Short hair, brown eyes, wearing simple glasses and a blue shirt."},
    )
    assert updated.status_code == 200
    revised = client.post(f"/api/v1/generations/{generation_id}/regenerate", headers=headers)
    assert revised.status_code == 200, revised.text
    assert revised.json()["image_count"] == 2
    assert len(revised.json()["images"]) == 2
    assert client.get("/api/v1/dashboard", headers=headers).json()["credits"] == 48


def test_failed_generation_refunds_credits(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_generator(settings: Settings, prompt: str, count: int) -> list[str]:
        raise ProviderRequestError("Provider unavailable")

    monkeypatch.setattr("app.api.generate_images", failing_generator)
    account = register(client)
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    created = client.post(
        "/api/v1/billing/payments",
        headers=headers,
        json={"pack_code": "starter", "method": "mpesa_till"},
    )
    reference = created.json()["instructions"]["account_reference"]
    client.post(
        "/api/v1/billing/manual/callback",
        json={
            "payment_reference": reference,
            "receipt_number": "REFUND123",
            "amount_kes": 500,
        },
        headers={"X-Payment-Webhook-Secret": "webhook-secret"},
    )

    failed = client.post(
        "/api/v1/generations",
        headers=headers,
        json={
            "title": "Portrait",
            "gender": "woman",
            "age_range": "25-34",
            "ethnicity": "East African",
            "description": "Natural portrait lighting and a friendly expression.",
        },
    )
    assert failed.status_code == 502
    dashboard = client.get("/api/v1/dashboard", headers=headers)
    assert dashboard.json()["credits"] == 60
    assert any(transaction["kind"] == "refund" for transaction in dashboard.json()["recent_transactions"])


def test_album_ownership_and_gallery_filter(client: TestClient) -> None:
    generated = client.post(
        "/api/v1/generations",
        json={
            "title": "Portrait",
            "gender": "woman",
            "age_range": "25-34",
            "ethnicity": "East African",
            "description": "A calm expression and natural portrait lighting.",
        },
    )
    image_id = generated.json()["generation"]["images"][0]["id"]
    account_response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "album-owner@example.com",
            "name": "Album Owner",
            "password": "secure-test-password",
            "guest_token": generated.json()["guest_token"],
        },
    )
    assert account_response.status_code == 201
    headers = {"Authorization": f"Bearer {account_response.json()['access_token']}"}
    album = client.post(
        "/api/v1/albums",
        headers=headers,
        json={"title": "Campaign", "description": "Spring campaign assets"},
    )
    assert album.status_code == 201
    album_id = album.json()["id"]

    attached = client.post(f"/api/v1/albums/{album_id}/images/{image_id}", headers=headers)
    assert attached.status_code == 200
    assert attached.json()["image_count"] == 1
    filtered = client.get(f"/api/v1/gallery?album_id={album_id}", headers=headers)
    assert [image["id"] for image in filtered.json()] == [image_id]

    other = register(client, "other@example.com")
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get(f"/api/v1/gallery?album_id={album_id}", headers=other_headers).status_code == 404
