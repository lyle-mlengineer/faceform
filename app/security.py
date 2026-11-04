from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    return bool(hashed_password) and password_hash.verify(password, hashed_password)


def _encode_token(payload: dict[str, Any], lifetime: timedelta) -> str:
    settings = get_settings()
    claims = payload | {"exp": datetime.now(timezone.utc) + lifetime}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    return _encode_token(
        {"sub": user_id, "type": "access"},
        timedelta(minutes=settings.access_token_minutes),
    )


def create_guest_token(session_id: str) -> str:
    return _encode_token({"sub": session_id, "type": "guest"}, timedelta(days=30))


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    settings = get_settings()
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if claims.get("type") != expected_type or not isinstance(claims.get("sub"), str):
        raise jwt.InvalidTokenError("Unexpected token type")
    return claims
