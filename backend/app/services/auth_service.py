import hashlib
import hmac
import secrets

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.auth import create_access_token
from app.core.database import SessionLocal
from app.models.work_model import User
from app.schemas.auth_schema import LoginRequest, RegisterRequest


class AuthService:
    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_password(password: str, stored: str) -> bool:
        # stored format: "<salt>$<sha256>"
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

    def login(self, payload: LoginRequest):
        db = SessionLocal()
        try:
            user = db.execute(
                select(User).where(User.email == payload.email)
            ).scalar_one_or_none()
            if not user or not self._verify_password(payload.password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="邮箱或密码错误",
                )

            token = create_access_token(user.id)
            return {
                "token": token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
            }
        finally:
            db.close()

    def register(self, payload: RegisterRequest):
        db = SessionLocal()
        try:
            exists = db.execute(
                select(User).where(User.email == payload.email)
            ).scalar_one_or_none()
            if exists:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该邮箱已注册",
                )

            user = User(
                username=payload.username.strip(),
                email=payload.email,
                password_hash=self._make_password_hash(payload.password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            token = create_access_token(user.id)
            return {
                "token": token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
            }
        finally:
            db.close()
