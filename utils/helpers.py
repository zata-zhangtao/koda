"""通用辅助函数模块

提供常用的纯函数工具，保持无状态、可复用。
"""

import json
from functools import lru_cache
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from utils.settings import config


@lru_cache(maxsize=1)
def get_app_timezone() -> ZoneInfo:
    """返回应用配置的时区对象.

    Returns:
        ZoneInfo: 当前应用使用的时区对象
    """
    return ZoneInfo(config.APP_TIMEZONE)


def get_app_timezone_name() -> str:
    """返回应用配置的时区名称.

    Returns:
        str: 当前应用使用的 IANA 时区名称
    """
    return config.APP_TIMEZONE


def utc_now_naive() -> datetime:
    """返回去掉时区信息的 UTC 当前时间.

    该项目当前的 SQLAlchemy `DateTime` 字段以 naive datetime 持久化，
    因此这里显式基于 UTC 生成时间，再移除 tzinfo，避免继续使用
    已弃用的 `datetime.utcnow()`.

    Returns:
        datetime: 以 UTC 为语义的 naive datetime

    Examples:
        >>> current_utc_datetime = utc_now_naive()
        >>> current_utc_datetime.tzinfo is None
        True
    """
    return datetime.now(UTC).replace(tzinfo=None)


def app_now_aware() -> datetime:
    """返回应用时区的当前 aware datetime.

    Returns:
        datetime: 带 `APP_TIMEZONE` 时区信息的当前时间
    """
    return datetime.now(get_app_timezone())


def utc_naive_to_app_aware(utc_datetime: datetime) -> datetime:
    """将 UTC 语义的 naive datetime 转为应用时区 aware datetime.

    如果传入值已经是 aware datetime，则会先归一化到 UTC，再转换到应用时区。

    Args:
        utc_datetime (datetime): 以 UTC 为语义的 naive datetime，
            或任意可转换到 UTC 的 aware datetime

    Returns:
        datetime: 转换后的应用时区 aware datetime
    """
    utc_aware_datetime = (
        utc_datetime.replace(tzinfo=UTC)
        if utc_datetime.tzinfo is None
        else utc_datetime.astimezone(UTC)
    )
    return utc_aware_datetime.astimezone(get_app_timezone())


def app_aware_to_utc_naive(app_datetime: datetime) -> datetime:
    """将应用时区输入时间转换为 UTC 语义的 naive datetime.

    若传入值缺少时区信息，默认按 `APP_TIMEZONE` 解释。该路径可直接复用于
    后续“用户手填 UTC+8 时间 -> 数据库存 UTC”的场景。

    Args:
        app_datetime (datetime): 应用时区 aware datetime，或按应用时区解释的 naive datetime

    Returns:
        datetime: 去除 tzinfo 的 UTC datetime
    """
    app_aware_datetime = (
        app_datetime.replace(tzinfo=get_app_timezone())
        if app_datetime.tzinfo is None
        else app_datetime.astimezone(get_app_timezone())
    )
    return app_aware_datetime.astimezone(UTC).replace(tzinfo=None)


def serialize_datetime_for_api(input_datetime: datetime | None) -> str | None:
    """将 datetime 序列化为带显式偏移的 ISO 8601 字符串.

    Args:
        input_datetime (datetime | None): 待序列化时间

    Returns:
        str | None: 应用时区 ISO 8601 字符串；若输入为空则返回 None
    """
    if input_datetime is None:
        return None
    return utc_naive_to_app_aware(input_datetime).isoformat()


def parse_iso_datetime_text(raw_datetime_text: str | None) -> datetime | None:
    """解析 ISO 8601 文本为 datetime 对象.

    若文本不带时区偏移，则按 UTC 语义解释，以兼容历史 naive API 输出。

    Args:
        raw_datetime_text (str | None): ISO 8601 时间字符串

    Returns:
        datetime | None: 解析后的 datetime，输入为空或解析失败时返回 None
    """
    if not raw_datetime_text:
        return None

    normalized_datetime_text = raw_datetime_text.strip()
    if normalized_datetime_text.endswith("Z"):
        normalized_datetime_text = normalized_datetime_text[:-1] + "+00:00"

    try:
        parsed_datetime = datetime.fromisoformat(normalized_datetime_text)
    except ValueError:
        return None

    if parsed_datetime.tzinfo is None:
        return parsed_datetime.replace(tzinfo=UTC)
    return parsed_datetime


def format_datetime_in_app_timezone(
    input_datetime: datetime | None,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str | None:
    """按应用时区格式化 datetime.

    Args:
        input_datetime (datetime | None): 待格式化时间
        fmt (str): `strftime` 格式字符串

    Returns:
        str | None: 格式化后的字符串；若输入为空则返回 None
    """
    if input_datetime is None:
        return None
    return utc_naive_to_app_aware(input_datetime).strftime(fmt)


def format_date_in_app_timezone(input_datetime: datetime | None) -> str | None:
    """按应用时区格式化日期部分.

    Args:
        input_datetime (datetime | None): 待格式化时间

    Returns:
        str | None: `YYYY-MM-DD` 日期字符串；若输入为空则返回 None
    """
    return format_datetime_in_app_timezone(input_datetime, "%Y-%m-%d")


def format_time_in_app_timezone(input_datetime: datetime | None) -> str | None:
    """按应用时区格式化时间部分.

    Args:
        input_datetime (datetime | None): 待格式化时间

    Returns:
        str | None: `HH:MM:SS` 时间字符串；若输入为空则返回 None
    """
    return format_datetime_in_app_timezone(input_datetime, "%H:%M:%S")


def get_app_timezone_offset_label(reference_datetime: datetime | None = None) -> str:
    """返回应用时区当前偏移标签.

    Args:
        reference_datetime (datetime | None): 用于计算偏移的参考时间，默认使用当前时间

    Returns:
        str: 形如 `UTC+08:00` 的偏移标签
    """
    reference_aware_datetime = (
        utc_naive_to_app_aware(reference_datetime)
        if reference_datetime is not None
        else app_now_aware()
    )
    offset_delta = reference_aware_datetime.utcoffset()
    total_offset_minutes = int(offset_delta.total_seconds() // 60) if offset_delta else 0
    sign_str = "+" if total_offset_minutes >= 0 else "-"
    absolute_offset_minutes = abs(total_offset_minutes)
    offset_hours, offset_minutes = divmod(absolute_offset_minutes, 60)
    return f"UTC{sign_str}{offset_hours:02d}:{offset_minutes:02d}"


def get_app_timezone_display_label(reference_datetime: datetime | None = None) -> str:
    """返回人类可读的应用时区标签.

    Args:
        reference_datetime (datetime | None): 用于计算偏移的参考时间

    Returns:
        str: 形如 `Asia/Shanghai (UTC+08:00)` 的标签
    """
    return (
        f"{get_app_timezone_name()} "
        f"({get_app_timezone_offset_label(reference_datetime)})"
    )


def parse_datetime(date_str: str, fmt: str = "%Y/%m/%d %H:%M") -> Optional[datetime]:
    """解析日期时间字符串为 datetime 对象

    Args:
        date_str (str): 日期时间字符串
        fmt (str): 日期时间格式，默认为 '%Y/%m/%d %H:%M'

    Returns:
        Optional[datetime]: 解析后的 datetime 对象，解析失败返回 None

    Examples:
        >>> from utils.helpers import parse_datetime
        >>> dt = parse_datetime("2025/12/01 16:00")
        >>> print(dt)
        2025-12-01 16:00:00
        >>> # 自定义格式
        >>> dt = parse_datetime("2025-12-01", fmt='%Y-%m-%d')
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, fmt)
    except ValueError:
        return None


def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """安全地解析 JSON 字符串

    Args:
        json_str (str): JSON 字符串
        default (Any): 解析失败时返回的默认值，默认为 None

    Returns:
        Any: 解析后的 Python 对象，失败返回 default

    Examples:
        >>> from utils.helpers import safe_json_loads
        >>> data = safe_json_loads('{"key": "value"}')
        >>> print(data)
        {'key': 'value'}
        >>> # 解析失败返回默认值
        >>> data = safe_json_loads('invalid json', default={})
        >>> print(data)
        {}
    """
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_get_nested(data: Dict, keys: List[str], default: Any = None) -> Any:
    """安全地获取嵌套字典中的值

    Args:
        data (Dict): 源字典
        keys (List[str]): 键路径列表
        default (Any): 获取失败时返回的默认值

    Returns:
        Any: 获取到的值，失败返回 default

    Examples:
        >>> from utils.helpers import safe_get_nested
        >>> data = {"a": {"b": {"c": 123}}}
        >>> value = safe_get_nested(data, ["a", "b", "c"])
        >>> print(value)
        123
        >>> # 键不存在时返回默认值
        >>> value = safe_get_nested(data, ["a", "x", "y"], default=0)
        >>> print(value)
        0
    """
    try:
        result = data
        for key in keys:
            result = result[key]
        return result
    except (KeyError, TypeError, IndexError):
        return default


def truncate_string(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """截断字符串到指定长度

    Args:
        text (str): 原始字符串
        max_length (int): 最大长度，默认 100
        suffix (str): 截断后的后缀，默认 "..."

    Returns:
        str: 截断后的字符串

    Examples:
        >>> from utils.helpers import truncate_string
        >>> text = "This is a very long string that needs to be truncated"
        >>> short = truncate_string(text, max_length=20)
        >>> print(short)
        This is a very lo...
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def normalize_whitespace(text: str) -> str:
    """标准化字符串中的空白字符

    将多个连续空白字符替换为单个空格，并去除首尾空白。

    Args:
        text (str): 原始字符串

    Returns:
        str: 标准化后的字符串

    Examples:
        >>> from utils.helpers import normalize_whitespace
        >>> text = "  hello   world  \\n  test  "
        >>> normalized = normalize_whitespace(text)
        >>> print(normalized)
        hello world test
    """
    return " ".join(text.split())


def chunks(lst: List, n: int) -> List[List]:
    """将列表分割为固定大小的块

    Args:
        lst (List): 原始列表
        n (int): 每块的大小

    Returns:
        List[List]: 分割后的列表

    Examples:
        >>> from utils.helpers import chunks
        >>> data = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        >>> result = chunks(data, 3)
        >>> print(result)
        [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    """
    return [lst[i : i + n] for i in range(0, len(lst), n)]


def retry_on_exception(
    func,
    max_retries: int = 3,
    delay: float = 1.0,
    exceptions: tuple = (Exception,),
    default=None,
):
    """对函数进行重试装饰

    Args:
        func: 要执行的函数
        max_retries (int): 最大重试次数
        delay (float): 重试间隔（秒）
        exceptions (tuple): 需要重试的异常类型
        default: 失败后返回的默认值

    Returns:
        函数执行结果或默认值

    Examples:
        >>> from utils.helpers import retry_on_exception
        >>> import requests
        >>>
        >>> def fetch_data():
        >>>     return requests.get("https://api.example.com/data")
        >>>
        >>> result = retry_on_exception(fetch_data, max_retries=3)
    """
    import time

    for attempt in range(max_retries):
        try:
            return func()
        except exceptions:
            if attempt == max_retries - 1:
                return default
            time.sleep(delay)
    return default
