from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FaceForm API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://faceform:faceform@localhost:5432/faceform"
    jwt_secret: str = "replace-this-with-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    credits_per_image: int = 6
    disable_credit_checks: bool = True
    credit_packs: list[dict[str, int | str]] = [
        {"code": "starter", "credits": 60, "amount_kes": 500},
        {"code": "creator", "credits": 150, "amount_kes": 1000},
        {"code": "studio", "credits": 400, "amount_kes": 2500},
    ]

    image_generation_api_url: str | None = None
    image_generation_api_key: str | None = None
    image_generation_model: str | None = None
    nvidia_api_key: SecretStr | None = None

    firebase_credentials: str | None = None
    firebase_web_api_key: str | None = None
    firebase_web_auth_domain: str | None = None
    firebase_web_project_id: str | None = None
    firebase_web_app_id: str | None = None

    mpesa_environment: str = "sandbox"
    mpesa_consumer_key: str | None = None
    mpesa_consumer_secret: str | None = None
    mpesa_shortcode: str | None = None
    mpesa_passkey: str | None = None
    mpesa_callback_url: str | None = None
    mpesa_merchant_name: str = "FaceForm"

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_success_url: str = "http://localhost:3000/billing/success"
    stripe_cancel_url: str = "http://localhost:3000/billing"
    payment_webhook_secret: str | None = None

    @property
    def credit_checks_disabled(self) -> bool:
        return self.disable_credit_checks and self.environment.casefold() == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
