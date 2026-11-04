from dataclasses import dataclass, field

from app.domain.events import (
    CreditsDebited,
    CreditsRefunded,
    GenerationCompleted,
    event_time,
)


@dataclass
class CreditBalance:
    user_id: str
    available: int

    def debit(self, amount: int, generation_id: str) -> CreditsDebited:
        if amount <= 0:
            raise ValueError("Credit debit must be positive")
        if self.available < amount:
            raise ValueError("Insufficient credits")
        self.available -= amount
        return CreditsDebited(
            occurred_at=event_time(),
            user_id=self.user_id,
            amount=amount,
            reason="Face generation",
            generation_id=generation_id,
        )

    def refund(self, amount: int, generation_id: str) -> CreditsRefunded:
        if amount <= 0:
            raise ValueError("Credit refund must be positive")
        self.available += amount
        return CreditsRefunded(
            occurred_at=event_time(),
            user_id=self.user_id,
            amount=amount,
            generation_id=generation_id,
        )


@dataclass
class FaceGeneration:
    id: str
    image_count: int
    status: str = "pending"
    events: list[GenerationCompleted] = field(default_factory=list)

    def complete(
        self,
        image_urls: list[str],
        variation_number: int | None = None,
    ) -> GenerationCompleted:
        if len(image_urls) != self.image_count:
            raise ValueError("The image provider returned an unexpected number of images")
        self.status = "completed"
        event = GenerationCompleted(
            occurred_at=event_time(),
            generation_id=self.id,
            image_urls=tuple(image_urls),
            variation_number=variation_number,
        )
        self.events.append(event)
        return event
