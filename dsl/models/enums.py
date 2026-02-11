"""DSL 枚举类型定义.

定义日志状态标记、任务生命周期状态和 AI 处理状态的枚举类.
"""

from enum import Enum


class DevLogStateTag(str, Enum):
    """日志状态标记，驱动任务生命周期.

    Attributes:
        NONE: 无特殊状态
        BUG: 发现 Bug (红色)
        OPTIMIZATION: 优化建议 (黄色)
        FIXED: 已修复 (绿色)
        TRANSFERRED: 已转移 (蓝色)
    """

    NONE = "NONE"
    BUG = "BUG"
    OPTIMIZATION = "OPTIMIZATION"
    FIXED = "FIXED"
    TRANSFERRED = "TRANSFERRED"


class TaskLifecycleStatus(str, Enum):
    """任务生命周期状态.

    Attributes:
        OPEN: 任务开启中
        CLOSED: 任务已关闭
        PENDING: 任务暂停/等待中
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"


class AIProcessingStatus(str, Enum):
    """AI 图片解析处理状态.

    Attributes:
        PENDING: 等待处理
        PROCESSING: 正在解析
        WAITING_REVIEW: 待校正
        CONFIRMED: 已确认
    """

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    WAITING_REVIEW = "WAITING_REVIEW"
    CONFIRMED = "CONFIRMED"
