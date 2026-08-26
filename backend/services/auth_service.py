import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from config import settings
from models.user import User


class AuthService:
    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        try:
            salt, digest = stored.split("$", 1)
        except ValueError:
            return False
        calc = AuthService._hash_password(password, salt)
        return hmac.compare_digest(calc, digest)

    @staticmethod
    def _make_password_hash(password: str) -> str:
        salt = secrets.token_hex(16)
        return f"{salt}${AuthService._hash_password(password, salt)}"

    @staticmethod
    def create_access_token(user_id: str) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "exp": now + timedelta(hours=72),
            "iat": now,
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

    @staticmethod
    def decode_access_token(token: str) -> dict:
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 已过期，请重新登录",
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 Token",
            )

    def login(self, db: Session, email: str, password: str):
        user = db.query(User).filter(User.email == email).first()
        if not user or not self._verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="邮箱或密码错误",
            )

        token = self.create_access_token(user.id)
        return {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            },
        }

    def register(self, db: Session, username: str, email: str, password: str):
        exists = db.query(User).filter(User.email == email).first()
        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该邮箱已注册",
            )

        user = User(
            username=username.strip(),
            email=email,
            password_hash=self._make_password_hash(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        token = self.create_access_token(user.id)
        return {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            },
        }

    def get_current_user(self, db: Session, token: str) -> User:
        payload = self.decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 Token payload",
            )

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在",
            )

        return user


auth_service = AuthService()
