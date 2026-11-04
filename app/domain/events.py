from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeAlias


@dataclass(frozen=True)
class DomainEvent:
    occurred_at: datetime


@dataclass(frozen=True)
class CreditsDebited(DomainEvent):
    user_id: str
    amount: int
    reason: str
    generation_id: str


@dataclass(frozen=True)
class CreditsRefunded(DomainEvent):
    user_id: str
    amount: int
    generation_id: str


@dataclass(frozen=True)
class PaymentSucceeded(DomainEvent):
    payment_id: str
    user_id: str
    credits: int
    amount_kes: int
    provider_reference: str


@dataclass(frozen=True)
class GenerationCompleted(DomainEvent):
    generation_id: str
    image_urls: tuple[str, ...]
    variation_number: int | None = None


DomainEventType: TypeAlias = CreditsDebited | CreditsRefunded | PaymentSucceeded | GenerationCompleted


def event_time() -> datetime:
    return datetime.now(timezone.utc)
