import hmac
import logging
from typing import Any
from uuid import uuid4

import firebase_admin
import jwt
import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials as firebase_credentials
from firebase_admin.exceptions import FirebaseError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.database import get_db
from app.domain.entities import CreditBalance, FaceGeneration
from app.domain.events import CreditsRefunded, GenerationCompleted, PaymentSucceeded, event_time
from app.models import Album, CreditTransaction, GeneratedImage, Generation, Payment, User
from app.providers import (
    ProviderConfigurationError,
    ProviderRequestError,
    create_mpesa_qr,
    create_stripe_checkout,
    generate_images,
    mpesa_is_configured,
    new_provider_reference,
    normalize_kenyan_phone,
    start_mpesa_stk,
)
from app.schemas import (
    AlbumCreateRequest,
    AlbumResponse,
    AlbumUpdateRequest,
    AuthResponse,
    CreditPackResponse,
    CreditTransactionResponse,
    DashboardResponse,
    FirebaseLoginRequest,
    GenerationCreatedResponse,
    GenerationRequest,
    GenerationResponse,
    GenerationUpdateRequest,
    ImageResponse,
    ImageUpdateRequest,
    LoginRequest,
    PaymentCreateRequest,
    PaymentCreatedResponse,
    PaymentResponse,
    RegisterRequest,
    UserResponse,
)
from app.security import create_access_token, create_guest_token, decode_token, hash_password, verify_password
from app.services import publish_domain_event

logger = logging.getLogger(__name__)
router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def settings_for(request: Request) -> Settings:
    return request.app.state.settings


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        claims = decode_token(credentials.credentials, "access")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc
    user = db.get(User, claims["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user


def optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        claims = decode_token(credentials.credentials, "access")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc
    user = db.get(User, claims["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user


def serialize_generation(generation: Generation) -> GenerationResponse:
    return GenerationResponse(
        id=generation.id,
        title=generation.title,
        gender=generation.gender,
        age_range=generation.age_range,
        ethnicity=generation.ethnicity,
        description=generation.description,
        image_count=generation.image_count,
        status=generation.status,
        error_message=generation.error_message,
        created_at=generation.created_at,
        images=[
            ImageResponse(
                id=image.id,
                generation_id=image.generation_id,
                url=image.url,
                title=image.title,
                created_at=image.created_at,
            )
            for image in generation.images
        ],
    )


def serialize_payment(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        pack_code=payment.pack_code,
        credits=payment.credits,
        amount_kes=payment.amount_kes,
        method=payment.method,
        status=payment.status,
        provider_reference=payment.provider_reference,
        receipt_number=payment.receipt_number,
        created_at=payment.created_at,
    )


def generation_prompt(generation: Generation) -> str:
    return (
        "Create a photorealistic portrait of a fictional, non-identifiable person, not based on any real individual. "
        f"Gender presentation: {generation.gender}. Age: {generation.age_range}. "
        f"Ethnicity: {generation.ethnicity}. Facial features and styling: {generation.description}. "
        "Natural anatomy, realistic skin texture, editorial studio lighting."
    )


def debit_user_credits(
    db: Session,
    user: User,
    amount: int,
    generation_id: str,
    disable_credit_checks: bool,
) -> int:
    if disable_credit_checks:
        return 0
    if user.credits < amount:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. This action requires {amount} credits.",
        )
    balance = CreditBalance(user_id=user.id, available=user.credits)
    event = balance.debit(amount, generation_id)
    result = db.execute(
        update(User)
        .where(User.id == user.id, User.credits >= amount)
        .values(credits=User.credits - amount)
        .execution_options(synchronize_session="fetch")
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. This action requires {amount} credits.",
        )
    publish_domain_event(db, event)
    return amount


def pack_for(settings: Settings, code: str) -> dict[str, Any]:
    for pack in settings.credit_packs:
        if pack.get("code") == code:
            credits, amount = pack.get("credits"), pack.get("amount_kes")
            if isinstance(credits, int) and credits > 0 and isinstance(amount, int) and amount > 0:
                return {"code": code, "credits": credits, "amount_kes": amount}
            break
    raise HTTPException(status_code=404, detail="Credit pack not found or is incorrectly configured.")


def claim_guest_generations(db: Session, user: User, token: str | None) -> int:
    if not token:
        return 0
    try:
        claims = decode_token(token, "guest")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail="Guest token is invalid or expired.") from exc
    rows = db.scalars(
        select(Generation).where(
            Generation.guest_session_id == claims["sub"],
            Generation.user_id.is_(None),
        )
    ).all()
    for generation in rows:
        generation.user_id = user.id
        generation.guest_session_id = None
        for image in generation.images:
            image.user_id = user.id
    return len(rows)


def authenticate_response(db: Session, user: User, guest_token: str | None = None) -> AuthResponse:
    claimed = claim_guest_generations(db, user, guest_token)
    db.commit()
    db.refresh(user)
    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserResponse.model_validate(user),
        claimed_generations=claimed,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/register", response_model=AuthResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = User(email=str(body.email).lower(), name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
        response = authenticate_response(db, user, body.guest_token)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    return response


@router.post("/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return authenticate_response(db, user, body.guest_token)


@router.post("/auth/firebase", response_model=AuthResponse)
def firebase_login(body: FirebaseLoginRequest, request: Request, db: Session = Depends(get_db)) -> AuthResponse:
    settings = settings_for(request)
    if not settings.firebase_credentials:
        raise HTTPException(status_code=503, detail="Firebase authentication is not configured.")
    try:
        try:
            app = firebase_admin.get_app("faceform")
        except ValueError:
            credential = firebase_credentials.Certificate(settings.firebase_credentials)
            app = firebase_admin.initialize_app(credential, name="faceform")
        claims = firebase_auth.verify_id_token(body.id_token, app=app)
    except (FirebaseError, ValueError) as exc:
        logger.warning("Firebase ID token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Firebase ID token is invalid or expired.") from exc
    email = claims.get("email")
    firebase_uid = claims.get("uid")
    if not isinstance(email, str) or not isinstance(firebase_uid, str) or not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="A verified Google email is required.")
    email = email.lower()
    user = db.scalar(select(User).where(User.firebase_uid == firebase_uid))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and user.firebase_uid not in (None, firebase_uid):
            raise HTTPException(status_code=409, detail="This email is linked to another social login.")
        if user is None:
            name = claims.get("name")
            user = User(email=email, name=name[:120] if isinstance(name, str) and name else email, firebase_uid=firebase_uid)
            db.add(user)
        else:
            user.firebase_uid = firebase_uid
    try:
        db.flush()
        return authenticate_response(db, user, body.guest_token)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This Firebase account is already linked.") from exc


@router.get("/auth/me", response_model=UserResponse)
def get_me(user: User = Depends(current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/generations", response_model=GenerationCreatedResponse, status_code=201)
async def create_generation(
    body: GenerationRequest,
    request: Request,
    x_guest_token: str | None = Header(default=None, alias="X-Guest-Token"),
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> GenerationCreatedResponse:
    settings = settings_for(request)
    if user is None and body.number_of_images != 1:
        raise HTTPException(status_code=400, detail="Guest accounts can generate one image. Sign in to generate more.")

    guest_session_id: str | None = None
    guest_token: str | None = None
    if user is None:
        if x_guest_token:
            try:
                guest_session_id = decode_token(x_guest_token, "guest")["sub"]
            except jwt.InvalidTokenError as exc:
                raise HTTPException(status_code=401, detail="Guest token is invalid or expired.") from exc
            existing = db.scalar(
                select(Generation.id).where(Generation.guest_session_id == guest_session_id)
            )
            if existing:
                raise HTTPException(status_code=409, detail="This guest session has already used its free generation.")
        else:
            guest_session_id = str(uuid4())
        guest_token = create_guest_token(guest_session_id)

    generation = Generation(
        user_id=user.id if user else None,
        guest_session_id=guest_session_id,
        title=body.title.strip(),
        gender=body.gender.strip(),
        age_range=body.age_range.strip(),
        ethnicity=body.ethnicity.strip(),
        description=body.description.strip(),
        image_count=body.number_of_images,
        status="processing",
    )
    charged = 0
    try:
        db.add(generation)
        db.flush()
        if user:
            amount = body.number_of_images * settings.credits_per_image
            charged = debit_user_credits(
                db, user, amount, generation.id, settings.credit_checks_disabled
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This guest session has already used its free generation.") from exc
    except HTTPException:
        db.rollback()
        raise

    domain_generation = FaceGeneration(id=generation.id, image_count=generation.image_count)
    try:
        provider = request.app.state.image_provider
        urls = await provider.generate_images(generation_prompt(generation), generation.image_count)
        urls = [request.url_for("images", path=f"{image}.png").__str__() for image in urls]
        event = domain_generation.complete(urls)
        publish_domain_event(db, event)
        db.commit()
    except (ProviderConfigurationError, ProviderRequestError, ValueError) as exc:
        db.rollback()
        generation = db.get(Generation, generation.id)
        if generation is not None:
            generation.status = "failed"
            generation.error_message = str(exc)[:1000]
            if user and charged:
                publish_domain_event(
                    db,
                    CreditsRefunded(
                        occurred_at=event_time(),
                        user_id=user.id,
                        amount=charged,
                        generation_id=generation.id,
                    ),
                )
            if not user:
                generation.guest_session_id = None
            db.commit()
        if isinstance(exc, ProviderConfigurationError):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        logger.exception("Face generation failed for generation %s", generation.id if generation else "unknown")
        detail = "The image provider failed to complete this generation."
        if charged:
            detail += " Credits were refunded."
        raise HTTPException(status_code=502, detail=detail) from exc

    result_generation = db.scalar(
        select(Generation).options(selectinload(Generation.images)).where(Generation.id == generation.id)
    )
    if result_generation is None:
        raise HTTPException(status_code=500, detail="Generation was completed but could not be loaded.")
    return GenerationCreatedResponse(
        generation=serialize_generation(result_generation),
        guest_token=guest_token,
        credits_charged=charged,
    )


@router.patch("/generations/{generation_id}", response_model=GenerationResponse)
def update_generation(
    generation_id: str,
    body: GenerationUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> GenerationResponse:
    generation = db.scalar(
        select(Generation)
        .options(selectinload(Generation.images))
        .where(Generation.id == generation_id, Generation.user_id == user.id)
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    for field in ("title", "gender", "age_range", "ethnicity", "description"):
        value = getattr(body, field)
        if value is not None:
            setattr(generation, field, value.strip())
    db.commit()
    return serialize_generation(generation)


@router.post("/generations/{generation_id}/regenerate", response_model=GenerationResponse)
async def regenerate_generation(
    generation_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> GenerationResponse:
    settings = settings_for(request)
    generation = db.scalar(
        select(Generation)
        .options(selectinload(Generation.images))
        .where(Generation.id == generation_id, Generation.user_id == user.id)
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    if generation.status == "processing":
        raise HTTPException(status_code=409, detail="This generation is already being processed.")

    charge = 0
    try:
        charge = debit_user_credits(
            db, user, settings.credits_per_image, generation.id, settings.credit_checks_disabled
        )
        generation.status = "processing"
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    try:
        urls = await generate_images(settings, generation_prompt(generation), 1)
        event = FaceGeneration(id=generation.id, image_count=1).complete(
            urls,
            variation_number=generation.image_count + 1,
        )
        generation.image_count += 1
        publish_domain_event(db, event)
        db.commit()
    except (ProviderConfigurationError, ProviderRequestError, ValueError) as exc:
        db.rollback()
        generation = db.get(Generation, generation_id)
        if generation is not None:
            generation.status = "completed" if generation.image_count else "failed"
            generation.error_message = str(exc)[:1000]
            if charge:
                publish_domain_event(
                    db,
                    CreditsRefunded(
                        occurred_at=event_time(),
                        user_id=user.id,
                        amount=charge,
                        generation_id=generation.id,
                    ),
                )
            db.commit()
        if isinstance(exc, ProviderConfigurationError):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        logger.exception("Face regeneration failed for generation %s", generation_id)
        detail = "The image provider failed to complete this edit."
        if charge:
            detail += " Credits were refunded."
        raise HTTPException(status_code=502, detail=detail) from exc

    result_generation = db.scalar(
        select(Generation).options(selectinload(Generation.images)).where(Generation.id == generation_id)
    )
    if result_generation is None:
        raise HTTPException(status_code=500, detail="Updated generation could not be loaded.")
    return serialize_generation(result_generation)


@router.get("/generations", response_model=list[GenerationResponse])
def list_generations(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[GenerationResponse]:
    rows = db.scalars(
        select(Generation)
        .options(selectinload(Generation.images))
        .where(Generation.user_id == user.id)
        .order_by(Generation.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [serialize_generation(row) for row in rows]


@router.get("/generations/{generation_id}", response_model=GenerationResponse)
def get_generation(
    generation_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> GenerationResponse:
    generation = db.scalar(
        select(Generation)
        .options(selectinload(Generation.images))
        .where(Generation.id == generation_id, Generation.user_id == user.id)
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return serialize_generation(generation)


@router.delete("/generations/{generation_id}", status_code=204)
def delete_generation(
    generation_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    generation = db.scalar(
        select(Generation).where(Generation.id == generation_id, Generation.user_id == user.id)
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found.")
    db.delete(generation)
    db.commit()


@router.get("/gallery", response_model=list[ImageResponse])
def list_gallery(
    album_id: str | None = None,
    limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[ImageResponse]:
    statement = select(GeneratedImage).where(GeneratedImage.user_id == user.id)
    if album_id:
        album = db.scalar(select(Album.id).where(Album.id == album_id, Album.user_id == user.id))
        if album is None:
            raise HTTPException(status_code=404, detail="Album not found.")
        statement = statement.join(GeneratedImage.albums).where(Album.id == album_id)
    images = db.scalars(
        statement.order_by(GeneratedImage.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return [
        ImageResponse(
            id=image.id,
            generation_id=image.generation_id,
            url=image.url,
            title=image.title,
            created_at=image.created_at,
        )
        for image in images
    ]


@router.patch("/images/{image_id}", response_model=ImageResponse)
def update_image(
    image_id: str,
    body: ImageUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ImageResponse:
    image = db.scalar(
        select(GeneratedImage).where(GeneratedImage.id == image_id, GeneratedImage.user_id == user.id)
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    image.title = body.title.strip()
    db.commit()
    db.refresh(image)
    return ImageResponse(
        id=image.id,
        generation_id=image.generation_id,
        url=image.url,
        title=image.title,
        created_at=image.created_at,
    )


@router.get("/images/{image_id}/download")
def download_image(
    image_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    image = db.scalar(
        select(GeneratedImage).where(GeneratedImage.id == image_id, GeneratedImage.user_id == user.id)
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    return RedirectResponse(image.url, status_code=307)


@router.delete("/images/{image_id}", status_code=204)
def delete_image(
    image_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    image = db.scalar(
        select(GeneratedImage).where(GeneratedImage.id == image_id, GeneratedImage.user_id == user.id)
    )
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    db.delete(image)
    db.commit()


def serialize_album(album: Album) -> AlbumResponse:
    return AlbumResponse(
        id=album.id,
        title=album.title,
        description=album.description,
        image_count=len(album.images),
        created_at=album.created_at,
    )


@router.get("/albums", response_model=list[AlbumResponse])
def list_albums(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[AlbumResponse]:
    albums = db.scalars(
        select(Album)
        .options(selectinload(Album.images))
        .where(Album.user_id == user.id)
        .order_by(Album.created_at.desc())
    ).all()
    return [serialize_album(album) for album in albums]


@router.post("/albums", response_model=AlbumResponse, status_code=201)
def create_album(
    body: AlbumCreateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AlbumResponse:
    album = Album(user_id=user.id, title=body.title.strip(), description=body.description.strip())
    db.add(album)
    db.commit()
    db.refresh(album)
    return serialize_album(album)


@router.patch("/albums/{album_id}", response_model=AlbumResponse)
def update_album(
    album_id: str,
    body: AlbumUpdateRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AlbumResponse:
    album = db.scalar(
        select(Album).options(selectinload(Album.images)).where(Album.id == album_id, Album.user_id == user.id)
    )
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found.")
    if body.title is not None:
        album.title = body.title.strip()
    if body.description is not None:
        album.description = body.description.strip()
    db.commit()
    db.refresh(album)
    return serialize_album(album)


@router.delete("/albums/{album_id}", status_code=204)
def delete_album(
    album_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    album = db.scalar(select(Album).where(Album.id == album_id, Album.user_id == user.id))
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found.")
    db.delete(album)
    db.commit()


@router.post("/albums/{album_id}/images/{image_id}", response_model=AlbumResponse)
def add_image_to_album(
    album_id: str,
    image_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AlbumResponse:
    album = db.scalar(
        select(Album).options(selectinload(Album.images)).where(Album.id == album_id, Album.user_id == user.id)
    )
    image = db.scalar(
        select(GeneratedImage).where(GeneratedImage.id == image_id, GeneratedImage.user_id == user.id)
    )
    if album is None or image is None:
        raise HTTPException(status_code=404, detail="Album or image not found.")
    if image not in album.images:
        album.images.append(image)
    db.commit()
    return serialize_album(album)


@router.delete("/albums/{album_id}/images/{image_id}", response_model=AlbumResponse)
def remove_image_from_album(
    album_id: str,
    image_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AlbumResponse:
    album = db.scalar(
        select(Album).options(selectinload(Album.images)).where(Album.id == album_id, Album.user_id == user.id)
    )
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found.")
    album.images = [image for image in album.images if image.id != image_id]
    db.commit()
    return serialize_album(album)


@router.get("/billing/packs", response_model=list[CreditPackResponse])
def list_credit_packs(request: Request) -> list[CreditPackResponse]:
    settings = settings_for(request)
    return [CreditPackResponse(**pack_for(settings, str(pack.get("code", "")))) for pack in settings.credit_packs]


@router.post("/billing/payments", response_model=PaymentCreatedResponse, status_code=201)
async def create_payment(
    body: PaymentCreateRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PaymentCreatedResponse:
    settings = settings_for(request)
    pack = pack_for(settings, body.pack_code)
    if body.method.startswith("mpesa") and not mpesa_is_configured(settings):
        raise HTTPException(status_code=503, detail="M-Pesa payments are not configured.")

    payment = Payment(
        user_id=user.id,
        pack_code=pack["code"],
        credits=pack["credits"],
        amount_kes=pack["amount_kes"],
        method=body.method,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    instructions: dict[str, str | int] = {}
    try:
        if body.method == "mpesa_stk":
            if not body.phone_number:
                raise HTTPException(status_code=422, detail="A phone number is required for an M-Pesa STK push.")
            reference = new_provider_reference()
            result = await start_mpesa_stk(settings, body.phone_number, payment.amount_kes, reference)
            payment.provider_reference = reference
            payment.checkout_request_id = result.get("CheckoutRequestID")
            if not payment.checkout_request_id:
                raise ProviderRequestError("M-Pesa did not return a checkout request ID.")
            instructions = {
                "message": str(result.get("CustomerMessage", "Approve the payment request on your phone.")),
                "checkout_request_id": payment.checkout_request_id,
            }
        elif body.method in ("mpesa_paybill", "mpesa_till"):
            reference = new_provider_reference()
            payment.provider_reference = reference
            instructions = {
                "payment_method": "Paybill" if body.method == "mpesa_paybill" else "Buy Goods / Till",
                "business_number": settings.mpesa_shortcode or "",
                "account_reference": reference,
                "amount_kes": payment.amount_kes,
            }
        elif body.method == "mpesa_qr":
            reference = new_provider_reference()
            payment.provider_reference = reference
            instructions = {
                "qr_code": await create_mpesa_qr(settings, payment.amount_kes, reference, "mpesa_paybill"),
                "account_reference": reference,
                "amount_kes": payment.amount_kes,
            }
        else:
            instructions = {
                "checkout_url": await create_stripe_checkout(
                    settings, payment.id, payment.amount_kes, payment.credits
                )
            }
        db.commit()
        db.refresh(payment)
    except HTTPException:
        db.rollback()
        db.refresh(payment)
        payment.status = "failed"
        db.commit()
        raise
    except (ProviderConfigurationError, ProviderRequestError, ValueError) as exc:
        db.rollback()
        payment = db.get(Payment, payment.id)
        if payment is not None:
            payment.status = "failed"
            db.commit()
        if isinstance(exc, ProviderConfigurationError):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        logger.exception("Payment provider request failed for payment %s", payment.id if payment else "unknown")
        raise HTTPException(status_code=502, detail="Payment provider could not start this payment.") from exc
    return PaymentCreatedResponse(payment=serialize_payment(payment), instructions=instructions)


@router.get("/billing/payments", response_model=list[PaymentResponse])
def list_payments(
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[PaymentResponse]:
    payments = db.scalars(
        select(Payment)
        .where(Payment.user_id == user.id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [serialize_payment(payment) for payment in payments]


@router.get("/billing/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    payment = db.scalar(select(Payment).where(Payment.id == payment_id, Payment.user_id == user.id))
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return serialize_payment(payment)


def settle_payment(db: Session, payment: Payment, provider_reference: str, receipt_number: str | None = None) -> bool:
    if payment.status == "paid":
        return False
    payment.status = "paid"
    if payment.provider_reference is None:
        payment.provider_reference = provider_reference
    payment.receipt_number = receipt_number
    publish_domain_event(
        db,
        PaymentSucceeded(
            occurred_at=event_time(),
            payment_id=payment.id,
            user_id=payment.user_id,
            credits=payment.credits,
            amount_kes=payment.amount_kes,
            provider_reference=provider_reference,
        ),
    )
    return True


@router.post("/billing/mpesa/callback")
async def mpesa_callback(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, int | str]:
    callback = payload.get("Body", {}).get("stkCallback", {}) if isinstance(payload.get("Body"), dict) else {}
    checkout_id = callback.get("CheckoutRequestID")
    if not isinstance(checkout_id, str):
        return {"ResultCode": 1, "ResultDesc": "Missing checkout request ID"}
    payment = db.scalar(select(Payment).where(Payment.checkout_request_id == checkout_id))
    if payment is None:
        logger.warning("M-Pesa callback did not match a payment")
        return {"ResultCode": 0, "ResultDesc": "Callback received"}
    if payment.status == "paid":
        return {"ResultCode": 0, "ResultDesc": "Callback received"}
    if callback.get("ResultCode") != 0:
        payment.status = "failed"
        db.commit()
        return {"ResultCode": 0, "ResultDesc": "Callback received"}

    metadata = callback.get("CallbackMetadata", {}).get("Item", [])
    values = {item.get("Name"): item.get("Value") for item in metadata if isinstance(item, dict)}
    amount = values.get("Amount")
    receipt = values.get("MpesaReceiptNumber")
    if not isinstance(amount, (int, float)) or int(amount) != payment.amount_kes or not isinstance(receipt, str):
        logger.error("M-Pesa callback did not match expected amount or receipt for payment %s", payment.id)
        payment.status = "failed"
        db.commit()
        return {"ResultCode": 0, "ResultDesc": "Callback received"}
    duplicate_receipt = db.scalar(
        select(Payment.id).where(Payment.receipt_number == receipt, Payment.id != payment.id)
    )
    if duplicate_receipt:
        logger.error("M-Pesa receipt was already applied to another payment")
        return {"ResultCode": 0, "ResultDesc": "Callback received"}
    settle_payment(db, payment, receipt, receipt)
    db.commit()
    return {"ResultCode": 0, "ResultDesc": "Callback received"}


@router.post("/billing/manual/callback")
async def manual_payment_callback(
    payload: dict[str, Any],
    request: Request,
    x_payment_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    secret = settings_for(request).payment_webhook_secret
    if not secret or not x_payment_webhook_secret or not hmac.compare_digest(secret, x_payment_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid payment webhook credentials.")
    reference = payload.get("payment_reference")
    receipt = payload.get("receipt_number")
    amount = payload.get("amount_kes")
    if not isinstance(reference, str) or not isinstance(receipt, str) or not isinstance(amount, int):
        raise HTTPException(status_code=422, detail="Payment reference, receipt number, and amount are required.")
    payment = db.scalar(select(Payment).where(Payment.provider_reference == reference))
    if payment is None or payment.method not in ("mpesa_paybill", "mpesa_till", "mpesa_qr"):
        raise HTTPException(status_code=404, detail="Pending manual M-Pesa payment not found.")
    if payment.amount_kes != amount:
        raise HTTPException(status_code=400, detail="Payment amount does not match the invoice.")
    duplicate_receipt = db.scalar(
        select(Payment.id).where(Payment.receipt_number == receipt, Payment.id != payment.id)
    )
    if duplicate_receipt:
        raise HTTPException(status_code=409, detail="This M-Pesa receipt has already been applied.")
    settle_payment(db, payment, receipt, receipt)
    db.commit()
    return {"status": "paid"}


@router.post("/billing/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    settings = settings_for(request)
    if not settings.stripe_webhook_secret or not stripe_signature:
        raise HTTPException(status_code=503, detail="Stripe webhook verification is not configured.")
    body = await request.body()
    try:
        event = stripe.Webhook.construct_event(body, stripe_signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature or payload.") from exc
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        payment_id = (session.get("metadata") or {}).get("payment_id")
        payment = db.get(Payment, payment_id) if payment_id else None
        if payment is not None and session.get("payment_status") == "paid":
            amount_total = session.get("amount_total")
            currency = session.get("currency")
            if amount_total != payment.amount_kes * 100 or currency != "kes":
                raise HTTPException(status_code=400, detail="Stripe payment amount does not match the invoice.")
            settle_payment(db, payment, str(session.get("payment_intent") or session.get("id")))
            db.commit()
    return {"status": "received"}


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    generations_count = db.scalar(
        select(func.count(Generation.id)).where(Generation.user_id == user.id)
    ) or 0
    images_count = db.scalar(
        select(func.count(GeneratedImage.id)).where(GeneratedImage.user_id == user.id)
    ) or 0
    albums_count = db.scalar(select(func.count(Album.id)).where(Album.user_id == user.id)) or 0
    transactions = db.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(10)
    ).all()
    return DashboardResponse(
        credits=user.credits,
        credits_per_image=settings_for(request).credits_per_image,
        credit_checks_disabled=settings_for(request).credit_checks_disabled,
        generations_count=generations_count,
        images_count=images_count,
        albums_count=albums_count,
        recent_transactions=[
            CreditTransactionResponse.model_validate(transaction) for transaction in transactions
        ],
    )
