"""Application configuration API routes."""

from fastapi import APIRouter

from backend.dsl.schemas.app_config_schema import AppConfigResponseSchema
from utils.helpers import get_app_timezone_offset_label
from utils.settings import config

router = APIRouter(prefix="/api/app-config", tags=["app-config"])


@router.get("", response_model=AppConfigResponseSchema)
def get_app_config() -> AppConfigResponseSchema:
    """Return the readonly runtime configuration used by the UI.

    Returns:
        AppConfigResponseSchema: Runtime configuration payload.
    """
    return AppConfigResponseSchema(
        app_timezone=config.APP_TIMEZONE,
        app_timezone_offset=get_app_timezone_offset_label(),
    )
