"""Short-lived identities signed by the trusted bot, never by public clients."""
import hashlib
import hmac
import time
from typing import Annotated

from fastapi import Header, HTTPException

from pdf_translator.config import settings


def issue_user_token(user_id: int, *, now: int | None = None) -> str:
    if len(settings.user_auth_secret) < 32:
        raise ValueError('USER_AUTH_SECRET must contain at least 32 characters')
    if user_id <= 0:
        raise ValueError('User ID must be positive')
    payload = f'{user_id}:{int(time.time()) if now is None else now}'
    signature = hmac.new(settings.user_auth_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f'{payload}:{signature}'


def require_user(x_user_token: Annotated[str | None, Header()] = None) -> int:
    if len(settings.user_auth_secret) < 32:
        raise HTTPException(status_code=503, detail='User authentication is not configured')
    try:
        user, timestamp, signature = (x_user_token or '').split(':')
        user_id, issued = int(user), int(timestamp)
        age = time.time() - issued
        expected = issue_user_token(user_id, now=issued).rsplit(':', 1)[1]
        if user != str(user_id) or timestamp != str(issued) or not -30 <= age <= 3600 or not hmac.compare_digest(signature, expected):
            raise ValueError('Invalid token')
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail='Missing, expired or invalid user token') from None
    return user_id
