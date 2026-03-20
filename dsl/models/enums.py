"""DSL 枚举类型定义.

定义日志状态标记、任务生命周期状态、工作流阶段和 AI 处理状态的枚举类.
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
        DELETED: 任务已删除（保留历史）
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"
    DELETED = "DELETED"


class WorkflowStage(str, Enum):
    """需求卡片工作流阶段，代表需求在自动化研发流程中的精确位置.

    Attributes:
        BACKLOG: 用户已提交，进入待办池，尚未启动
        PRD_GENERATING: AI 正在生成 PRD 文档
        PRD_WAITING_CONFIRMATION: PRD 已生成，等待用户确认
        IMPLEMENTATION_IN_PROGRESS: 用户确认后，AI 正在无打扰编码
        SELF_REVIEW_IN_PROGRESS: 编码完成，AI 正在执行自检与代码评审
        TEST_IN_PROGRESS: 自检通过，拉起容器执行自动化测试
        PR_PREPARING: 测试通过，正在整理变更并创建 PR
        ACCEPTANCE_IN_PROGRESS: PR 已创建，验收员或用户正在验收
        CHANGES_REQUESTED: AI 无法自行完成闭环或人工要求修改，等待人工介入后重新执行
        DONE: 需求验收完成，已关闭
    """

    BACKLOG = "backlog"
    PRD_GENERATING = "prd_generating"
    PRD_WAITING_CONFIRMATION = "prd_waiting_confirmation"
    IMPLEMENTATION_IN_PROGRESS = "implementation_in_progress"
    SELF_REVIEW_IN_PROGRESS = "self_review_in_progress"
    TEST_IN_PROGRESS = "test_in_progress"
    PR_PREPARING = "pr_preparing"
    ACCEPTANCE_IN_PROGRESS = "acceptance_in_progress"
    CHANGES_REQUESTED = "changes_requested"
    DONE = "done"


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
