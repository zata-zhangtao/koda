"""Application configuration response schemas."""

from backend.dsl.schemas.base import DSLResponseSchema


class AppConfigResponseSchema(DSLResponseSchema):
    """Readonly runtime configuration exposed to the frontend.

    Attributes:
        app_timezone (str): The configured IANA timezone name.
        app_timezone_offset (str): The current UTC offset label for the timezone.
    """

    app_timezone: str
    app_timezone_offset: str
