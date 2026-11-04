from sqlalchemy.orm import Session

from app.domain.events import (
    CreditsDebited,
    CreditsRefunded,
    DomainEventType,
    GenerationCompleted,
    PaymentSucceeded,
)
from app.models import CreditTransaction, GeneratedImage, Generation, Payment, User


def publish_domain_event(db: Session, event: DomainEventType) -> None:
    if isinstance(event, CreditsDebited):
        db.add(
            CreditTransaction(
                user_id=event.user_id,
                kind="debit",
                credits=-event.amount,
                description=event.reason,
                reference_id=event.generation_id,
            )
        )
    elif isinstance(event, CreditsRefunded):
        user = db.get(User, event.user_id)
        if user is None:
            raise RuntimeError("Cannot refund credits: account no longer exists.")
        user.credits += event.amount
        db.add(
            CreditTransaction(
                user_id=event.user_id,
                kind="refund",
                credits=event.amount,
                description="Generation provider failure refund",
                reference_id=event.generation_id,
            )
        )
    elif isinstance(event, PaymentSucceeded):
        user = db.get(User, event.user_id)
        payment = db.get(Payment, event.payment_id)
        if user is None or payment is None:
            raise RuntimeError("Cannot apply payment: account or payment no longer exists.")
        user.credits += event.credits
        db.add(
            CreditTransaction(
                user_id=event.user_id,
                kind="purchase",
                credits=event.credits,
                description=f"Purchased {event.credits} credits ({event.amount_kes} KES)",
                reference_id=event.payment_id,
            )
        )
    elif isinstance(event, GenerationCompleted):
        generation = db.get(Generation, event.generation_id)
        if generation is None:
            raise RuntimeError("Cannot complete generation: it no longer exists.")
        generation.status = "completed"
        generation.error_message = None
        for index, url in enumerate(event.image_urls, start=1):
            generation.images.append(
                GeneratedImage(
                    generation_id=generation.id,
                    user_id=generation.user_id,
                    url=url,
                    title=(
                        f"{generation.title} variation {event.variation_number}"
                        if event.variation_number is not None
                        else f"{generation.title} {index}"
                    ),
                )
            )
    else:
        raise TypeError(f"Unsupported domain event: {type(event).__name__}")
