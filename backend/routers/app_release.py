from fastapi import APIRouter

from config import settings


router = APIRouter(tags=["app-release"])


@router.get("/app/release")
def get_app_release() -> dict[str, str | int]:
    return {
        "version_name": settings.mobile_version_name,
        "version_code": settings.mobile_version_code,
        "download_url": settings.mobile_download_url,
    }
