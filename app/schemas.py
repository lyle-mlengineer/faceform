from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    guest_token: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    guest_token: str | None = None


class FirebaseLoginRequest(BaseModel):
    id_token: str = Field(min_length=20)
    guest_token: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    name: str
    credits: int
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
    claimed_generations: int = 0


class GenerationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    gender: str = Field(min_length=1, max_length=40)
    age_range: str = Field(min_length=1, max_length=40)
    ethnicity: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=10, max_length=2000)
    number_of_images: int = Field(default=1, ge=1, le=4)

    @field_validator("title", "gender", "age_range", "ethnicity", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class GenerationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    gender: str | None = Field(default=None, min_length=1, max_length=40)
    age_range: str | None = Field(default=None, min_length=1, max_length=40)
    ethnicity: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, min_length=10, max_length=2000)

    @field_validator("title", "gender", "age_range", "ethnicity", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_an_update(self) -> "GenerationUpdateRequest":
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("At least one generation field must be provided.")
        return self


class ImageResponse(BaseModel):
    id: str
    generation_id: str
    url: str
    title: str
    created_at: datetime


class GenerationResponse(BaseModel):
    id: str
    title: str
    gender: str
    age_range: str
    ethnicity: str
    description: str
    image_count: int
    status: str
    error_message: str | None
    created_at: datetime
    images: list[ImageResponse]


class GenerationCreatedResponse(BaseModel):
    generation: GenerationResponse
    guest_token: str | None = None
    credits_charged: int = 0


class AlbumCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class AlbumUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class AlbumResponse(BaseModel):
    id: str
    title: str
    description: str
    image_count: int
    created_at: datetime


class ImageUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class CreditPackResponse(BaseModel):
    code: str
    credits: int
    amount_kes: int
    currency: Literal["KES"] = "KES"


class PaymentCreateRequest(BaseModel):
    pack_code: str = Field(min_length=1, max_length=40)
    method: Literal["mpesa_stk", "mpesa_paybill", "mpesa_till", "mpesa_qr", "card"]
    phone_number: str | None = Field(default=None, max_length=20)


class PaymentResponse(BaseModel):
    id: str
    pack_code: str
    credits: int
    amount_kes: int
    currency: Literal["KES"] = "KES"
    method: str
    status: str
    provider_reference: str | None
    receipt_number: str | None
    created_at: datetime


class PaymentCreatedResponse(BaseModel):
    payment: PaymentResponse
    instructions: dict[str, str | int] = Field(default_factory=dict)


class CreditTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    credits: int
    description: str
    reference_id: str | None
    created_at: datetime


class DashboardResponse(BaseModel):
    credits: int
    credits_per_image: int
    credit_checks_disabled: bool
    generations_count: int
    images_count: int
    albums_count: int
    recent_transactions: list[CreditTransactionResponse]
