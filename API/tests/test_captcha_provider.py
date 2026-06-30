"""Captcha provider + service unit tests.

Image-captcha is stateless (fernet-encrypted token carries the answer)
so no DB / no HTTP needed here.
"""

from __future__ import annotations

import time
from unittest.mock import patch

from src.app.core.auth.captcha import service as captcha_service
from src.app.shared.providers import captcha as captcha_provider
from src.utilities.fernet_util import fernet


def test_generate_captcha_returns_image_and_token():
    out = captcha_provider.generate_captcha()
    assert set(out.keys()) == {"image", "token"}
    assert out["image"] and out["token"]


def test_verify_captcha_accepts_correct_answer():
    token = fernet.encrypt(f"ABCDE|{int(time.time())}")
    assert captcha_provider.verify_captcha(token, "ABCDE") is True


def test_verify_captcha_is_case_insensitive():
    token = fernet.encrypt(f"ABCDE|{int(time.time())}")
    assert captcha_provider.verify_captcha(token, "abcde") is True


def test_verify_captcha_rejects_wrong_answer():
    token = fernet.encrypt(f"ABCDE|{int(time.time())}")
    assert captcha_provider.verify_captcha(token, "WRONG") is False


def test_verify_captcha_rejects_expired_token():
    old_ts = int(time.time()) - captcha_provider.CAPTCHA_EXPIRY_SECONDS - 1
    token = fernet.encrypt(f"ABCDE|{old_ts}")
    assert captcha_provider.verify_captcha(token, "ABCDE") is False


def test_verify_captcha_rejects_garbage_token():
    assert captcha_provider.verify_captcha("not-a-fernet-token", "ABCDE") is False


def test_issue_challenge_returns_none_when_disabled():
    with patch.object(captcha_service, "CAPTCHA_TYPE", "none"):
        ch = captcha_service.issue_challenge()
    assert ch.type == "none"
    assert ch.image is None and ch.token is None and ch.site_key is None


def test_issue_challenge_returns_image_challenge():
    with patch.object(captcha_service, "CAPTCHA_TYPE", "image"):
        ch = captcha_service.issue_challenge()
    assert ch.type == "image"
    assert ch.image and ch.token
    assert ch.site_key is None


def test_issue_challenge_returns_recaptcha_site_key():
    with (
        patch.object(captcha_service, "CAPTCHA_TYPE", "recaptcha_v2"),
        patch.object(captcha_service, "RECAPTCHA_SITE_KEY", "test-site-key"),
    ):
        ch = captcha_service.issue_challenge()
    assert ch.type == "recaptcha_v2"
    assert ch.site_key == "test-site-key"
    assert ch.image is None and ch.token is None
