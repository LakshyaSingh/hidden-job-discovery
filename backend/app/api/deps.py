"""Shared FastAPI dependencies."""
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_admin_key(x_api_key: str | None = Header(default=None)) -> None:
    """Guard admin/write endpoints with a shared secret.

    If ``ADMIN_API_KEY`` is unset (local/dev), protection is disabled and the
    request passes. In any public deployment, set it — then callers must send a
    matching ``X-API-Key`` header. Compared in constant time.
    """
    expected = get_settings().admin_api_key
    if not expected:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-API-Key",
        )
