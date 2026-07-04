"""Tests for the admin API-key guard on write endpoints."""
import pytest
from fastapi import HTTPException

from app.api.deps import require_admin_key
from app.config import get_settings


async def test_open_when_no_key_configured(monkeypatch):
    # Empty key → protection disabled (local/dev): any request passes.
    monkeypatch.setattr(get_settings(), "admin_api_key", "")
    await require_admin_key(x_api_key=None)
    await require_admin_key(x_api_key="anything")


async def test_rejects_missing_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_key", "s3cret")
    with pytest.raises(HTTPException) as exc:
        await require_admin_key(x_api_key=None)
    assert exc.value.status_code == 401


async def test_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_key", "s3cret")
    with pytest.raises(HTTPException) as exc:
        await require_admin_key(x_api_key="wrong")
    assert exc.value.status_code == 401


async def test_accepts_correct_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_key", "s3cret")
    await require_admin_key(x_api_key="s3cret")  # no raise
