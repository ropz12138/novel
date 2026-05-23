"""Tests for JWT authentication: token creation, decoding, expiration, invalid tokens."""
import sys
sys.path.insert(0, "/root/Novel/backend")

import time
from unittest.mock import MagicMock, patch

import jwt


class TestCreateAccessToken:
    """JWT token creation tests."""

    def test_create_token_contains_sub(self):
        from app.core.auth import create_access_token

        token = create_access_token(user_id="user-123")
        payload = jwt.decode(token, options={"verify_signature": False})
        assert payload["sub"] == "user-123"

    def test_create_token_contains_exp(self):
        from app.core.auth import create_access_token

        token = create_access_token(user_id="user-123")
        payload = jwt.decode(token, options={"verify_signature": False})
        assert "exp" in payload

    def test_create_token_is_string(self):
        from app.core.auth import create_access_token

        token = create_access_token(user_id="user-123")
        assert isinstance(token, str)


class TestDecodeAccessToken:
    """JWT token decoding and validation tests."""

    def test_decode_valid_token(self):
        from app.core.auth import create_access_token, decode_access_token

        token = create_access_token(user_id="user-123")
        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"

    def test_decode_expired_token(self):
        from app.core.auth import decode_access_token

        from app.core.config import settings
        expired_token = jwt.encode(
            {"sub": "user-123", "exp": int(time.time()) - 3600},
            settings.jwt_secret,
            algorithm="HS256",
        )
        try:
            decode_access_token(expired_token)
            assert False, "Should have raised an exception"
        except Exception as exc:
            assert exc.status_code == 401

    def test_decode_invalid_signature(self):
        from app.core.auth import decode_access_token

        bad_token = jwt.encode(
            {"sub": "user-123", "exp": int(time.time()) + 3600},
            "wrong-secret-key",
            algorithm="HS256",
        )
        try:
            decode_access_token(bad_token)
            assert False, "Should have raised an exception"
        except Exception as exc:
            assert exc.status_code == 401

    def test_decode_malformed_token(self):
        from app.core.auth import decode_access_token

        try:
            decode_access_token("not.a.valid.token")
            assert False, "Should have raised an exception"
        except Exception as exc:
            assert exc.status_code == 401


class TestGetCurrentUser:
    """get_current_user dependency injection tests."""

    def test_valid_token_returns_user(self):
        from app.core.auth import create_access_token, get_current_user

        token = create_access_token(user_id="user-123")

        mock_user = MagicMock()
        mock_user.id = "user-123"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_user

        result = get_current_user(token=token, db=mock_db)
        assert result.id == "user-123"

    def test_missing_token_raises_401(self):
        from app.core.auth import get_current_user

        mock_db = MagicMock()
        try:
            get_current_user(token=None, db=mock_db)
            assert False, "Should have raised 401"
        except Exception as exc:
            assert exc.status_code == 401

    def test_user_not_found_raises_401(self):
        from app.core.auth import create_access_token, get_current_user

        token = create_access_token(user_id="nonexistent-user")

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        try:
            get_current_user(token=token, db=mock_db)
            assert False, "Should have raised 401"
        except Exception as exc:
            assert exc.status_code == 401

    def test_invalid_token_raises_401(self):
        from app.core.auth import get_current_user

        mock_db = MagicMock()
        try:
            get_current_user(token="invalid-token", db=mock_db)
            assert False, "Should have raised 401"
        except Exception as exc:
            assert exc.status_code == 401
