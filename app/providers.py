import base64
import io
import secrets
from datetime import datetime
from typing import Any

import httpx
import qrcode

from app.config import Settings


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


class Provider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_images(self, prompt: str, count: int) -> list[str]:
        ...


async def generate_images(settings: Settings, prompt: str, count: int) -> list[str]:
    if not settings.image_generation_api_url or not settings.image_generation_api_key:
        raise ProviderConfigurationError(
            "Image generation is not configured. Set IMAGE_GENERATION_API_URL and IMAGE_GENERATION_API_KEY."
        )

    payload: dict[str, Any] = {
        "prompt": prompt,
        "n": count,
        "size": "1024x1024",
        "response_format": "url",
    }
    if settings.image_generation_model:
        payload["model"] = settings.image_generation_model

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                settings.image_generation_api_url,
                headers={"Authorization": f"Bearer {settings.image_generation_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderRequestError(f"Image generation provider request failed: {exc}") from exc

    data = body.get("data") if isinstance(body, dict) else None
    urls = [item.get("url") for item in data or [] if isinstance(item, dict)]
    if len(urls) != count or any(not isinstance(url, str) or not url.startswith(("https://", "http://")) for url in urls):
        raise ProviderRequestError("Image provider response must contain one hosted image URL per requested image.")
    return urls


def mpesa_base_url(settings: Settings) -> str:
    if settings.mpesa_environment == "production":
        return "https://api.safaricom.co.ke"
    return "https://sandbox.safaricom.co.ke"


def mpesa_is_configured(settings: Settings) -> bool:
    return all(
        (
            settings.mpesa_consumer_key,
            settings.mpesa_consumer_secret,
            settings.mpesa_shortcode,
            settings.mpesa_passkey,
            settings.mpesa_callback_url,
        )
    )


async def mpesa_access_token(settings: Settings) -> str:
    if not mpesa_is_configured(settings):
        raise ProviderConfigurationError("M-Pesa is not configured. Add the Daraja credentials and callback URL.")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{mpesa_base_url(settings)}/oauth/v1/generate",
                params={"grant_type": "client_credentials"},
                auth=(settings.mpesa_consumer_key or "", settings.mpesa_consumer_secret or ""),
            )
            response.raise_for_status()
            token = response.json().get("access_token")
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderRequestError(f"Could not authenticate with M-Pesa: {exc}") from exc
    if not isinstance(token, str):
        raise ProviderRequestError("M-Pesa did not return an access token.")
    return token


async def start_mpesa_stk(
    settings: Settings,
    phone_number: str,
    amount_kes: int,
    reference: str,
) -> dict[str, Any]:
    token = await mpesa_access_token(settings)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{settings.mpesa_shortcode}{settings.mpesa_passkey}{timestamp}".encode()
    ).decode()
    phone = normalize_kenyan_phone(phone_number)
    payload = {
        "BusinessShortCode": settings.mpesa_shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount_kes,
        "PartyA": phone,
        "PartyB": settings.mpesa_shortcode,
        "PhoneNumber": phone,
        "CallBackURL": settings.mpesa_callback_url,
        "AccountReference": reference[:12],
        "TransactionDesc": "FaceForm credits",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{mpesa_base_url(settings)}/mpesa/stkpush/v1/processrequest",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderRequestError(f"M-Pesa STK request failed: {exc}") from exc
    if result.get("ResponseCode") != "0":
        raise ProviderRequestError(result.get("ResponseDescription", "M-Pesa rejected the STK request."))
    return result


async def create_mpesa_qr(
    settings: Settings,
    amount_kes: int,
    reference: str,
    method: str,
) -> str:
    token = await mpesa_access_token(settings)
    payload = {
        "MerchantName": settings.mpesa_merchant_name,
        "RefNo": reference[:20],
        "Amount": amount_kes,
        "TrxCode": "BG" if method == "mpesa_till" else "PB",
        "CPI": settings.mpesa_shortcode,
        "Size": "300",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{mpesa_base_url(settings)}/mpesa/qrcode/v1/generate",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderRequestError(f"M-Pesa QR request failed: {exc}") from exc
    encoded = result.get("QRCode")
    if not isinstance(encoded, str):
        raise ProviderRequestError("M-Pesa did not return a QR code.")
    return f"data:image/png;base64,{encoded}"


def normalize_kenyan_phone(phone_number: str) -> str:
    digits = "".join(char for char in phone_number if char.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = f"254{digits[1:]}"
    if digits.startswith("254") and len(digits) == 12:
        return digits
    raise ValueError("Enter a valid Kenyan mobile number, such as 0712345678 or +254712345678.")


def create_instructions_qr(payload: str) -> str:
    image = qrcode.make(payload)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"


async def create_stripe_checkout(settings: Settings, payment_id: str, amount_kes: int, credits: int) -> str:
    if not settings.stripe_secret_key:
        raise ProviderConfigurationError("Card payment is not configured. Set STRIPE_SECRET_KEY.")
    form = {
        "mode": "payment",
        "success_url": settings.stripe_success_url,
        "cancel_url": settings.stripe_cancel_url,
        "client_reference_id": payment_id,
        "metadata[payment_id]": payment_id,
        "metadata[credits]": str(credits),
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "kes",
        "line_items[0][price_data][unit_amount]": str(amount_kes * 100),
        "line_items[0][price_data][product_data][name]": f"FaceForm {credits} credits",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(settings.stripe_secret_key, ""),
                data=form,
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderRequestError(f"Card checkout creation failed: {exc}") from exc
    if not isinstance(result.get("url"), str):
        raise ProviderRequestError("Stripe did not return a checkout URL.")
    return result["url"]


def new_provider_reference() -> str:
    return f"FF{secrets.token_hex(5).upper()}"
