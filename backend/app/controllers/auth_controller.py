from app.schemas.auth_schema import LoginRequest, RegisterRequest
from app.services.auth_service import AuthService

service = AuthService()


def login(payload: LoginRequest):
    return service.login(payload)


def register(payload: RegisterRequest):
    return service.register(payload)
