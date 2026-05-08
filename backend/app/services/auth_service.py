from fastapi import HTTPException, status

from app.schemas.auth_schema import LoginRequest, RegisterRequest


class AuthService:
    def login(self, payload: LoginRequest):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="login is not implemented yet"
        )

    def register(self, payload: RegisterRequest):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="register is not implemented yet"
        )
