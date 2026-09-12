import pytest


@pytest.fixture(autouse=True)
def _explicit_test_security_mode(monkeypatch):
    """Legacy functional tests run with HTTP auth explicitly disabled.

    Production remains secure-by-default. Dedicated security tests override this
    environment flag and exercise the real role/session/CSRF/idempotency path.
    """
    monkeypatch.setenv('VISION_SECURITY_DISABLED','1')
