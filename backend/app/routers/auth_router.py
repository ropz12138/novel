from fastapi import APIRouter

from app.controllers.auth_controller import login, register
from app.schemas.auth_schema import LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login_api(payload: LoginRequest):
    return login(payload)


@router.post("/register")
def register_api(payload: RegisterRequest):
    return register(payload)
