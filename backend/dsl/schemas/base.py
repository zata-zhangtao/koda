"""共享 Pydantic Schema 基类.

提供 ORM 读取能力与统一的 datetime JSON 序列化策略。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, field_serializer

from utils.helpers import serialize_datetime_for_api


class DSLBaseSchema(BaseModel):
    """DSL Schema 基类.

    统一开启 `from_attributes=True`，便于直接从 ORM 模型构建响应。
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)


class DSLResponseSchema(DSLBaseSchema):
    """DSL 响应 Schema 基类.

    所有 datetime 字段在 JSON 输出阶段都会被转换为应用时区且带显式偏移。
    """

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_datetime_fields(self, field_value: Any) -> Any:
        """序列化响应中的 datetime 字段.

        Args:
            field_value: 当前字段值

        Returns:
            Any: datetime 字段会被转换为 ISO 8601 字符串，其他字段原样返回
        """
        if isinstance(field_value, datetime):
            return serialize_datetime_for_api(field_value)
        return field_value
