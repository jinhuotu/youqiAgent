"""启动校验与安全工具最小测试。"""

import pytest

from app.core.config import Settings
from app.core.startup import validate_settings


def test_validate_settings_production_requires_tokens() -> None:
    settings = Settings(
        env="production",
        internal_service_tokens="",
        encryption_key="your_fernet_encryption_key_here_change_me",
    )
    with pytest.raises(RuntimeError, match="INTERNAL_SERVICE_TOKENS"):
        validate_settings(settings)


def test_validate_settings_dev_allows_missing_encryption(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        env="development",
        internal_service_tokens="tok-a",
        encryption_key="",
    )
    # 不应抛错
    validate_settings(settings)


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    from app.core import security
    from app.core.config import Settings

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: Settings(encryption_key=key, internal_service_tokens="tok"),
    )

    cipher = security.encrypt_text("sk-test-secret")
    assert cipher != "sk-test-secret"
    assert security.decrypt_text(cipher) == "sk-test-secret"
