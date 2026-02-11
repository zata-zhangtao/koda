"""RunAccount API 路由.

提供运行账户的创建、查询和切换功能.
"""

import getpass
import platform
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from dsl.models.run_account import RunAccount
from dsl.schemas.run_account_schema import (
    RunAccountCreateSchema,
    RunAccountResponseSchema,
)
from utils.database import get_db
from utils.logger import logger

router = APIRouter(prefix="/api/run-accounts", tags=["run-accounts"])


@router.get("", response_model=list[RunAccountResponseSchema])
def list_run_accounts(
    db_session: Annotated[Session, Depends(get_db)],
) -> list[RunAccount]:
    """列出所有运行账户.

    Args:
        db_session: 数据库会话

    Returns:
        list[RunAccount]: 账户列表，按创建时间倒序排列
    """
    accounts = db_session.query(RunAccount).order_by(RunAccount.created_at.desc()).all()
    return accounts


@router.post("", response_model=RunAccountResponseSchema, status_code=status.HTTP_201_CREATED)
def create_run_account(
    account_create_schema: RunAccountCreateSchema,
    db_session: Annotated[Session, Depends(get_db)],
) -> RunAccount:
    """创建新的运行账户.

    创建新账户时，会自动将其他账户设为非活跃状态。

    Args:
        account_create_schema: 账户创建数据
        db_session: 数据库会话

    Returns:
        RunAccount: 新创建的账户
    """
    # 生成显示名称
    display_name = account_create_schema.account_display_name
    if not display_name:
        branch_suffix = (
            f" @ {account_create_schema.git_branch_name}"
            if account_create_schema.git_branch_name
            else ""
        )
        display_name = f"{account_create_schema.user_name} @ {account_create_schema.environment_os}{branch_suffix}"

    # 将其他账户设为非活跃
    db_session.query(RunAccount).update({RunAccount.is_active: False})

    new_account = RunAccount(
        account_display_name=display_name,
        user_name=account_create_schema.user_name,
        environment_os=account_create_schema.environment_os,
        git_branch_name=account_create_schema.git_branch_name,
        is_active=True,
    )

    db_session.add(new_account)
    db_session.commit()
    db_session.refresh(new_account)

    logger.info(f"Created RunAccount: {new_account.id[:8]}... - {display_name}")
    return new_account


@router.put("/{account_id}/activate", response_model=RunAccountResponseSchema)
def activate_run_account(
    account_id: str,
    db_session: Annotated[Session, Depends(get_db)],
) -> RunAccount:
    """切换活跃账户.

    将指定账户设为活跃，同时将所有其他账户设为非活跃。

    Args:
        account_id: 要激活的账户 ID
        db_session: 数据库会话

    Returns:
        RunAccount: 激活后的账户

    Raises:
        HTTPException: 当账户不存在时返回 404
    """
    account = db_session.query(RunAccount).filter(RunAccount.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RunAccount with id {account_id} not found",
        )

    # 将所有账户设为非活跃
    db_session.query(RunAccount).update({RunAccount.is_active: False})

    # 激活指定账户
    account.is_active = True
    db_session.commit()
    db_session.refresh(account)

    logger.info(f"Activated RunAccount: {account_id[:8]}...")
    return account


@router.get("/current", response_model=RunAccountResponseSchema)
def get_current_run_account(
    db_session: Annotated[Session, Depends(get_db)],
) -> RunAccount:
    """获取当前活跃账户.

    如果没有活跃账户，自动创建一个默认账户。

    Args:
        db_session: 数据库会话

    Returns:
        RunAccount: 当前活跃账户
    """
    account = (
        db_session.query(RunAccount).filter(RunAccount.is_active == True).first()
    )

    if account:
        return account

    # 自动创建默认账户
    try:
        user_name = getpass.getuser()
    except Exception:
        user_name = "developer"

    environment_os = platform.system()

    # 尝试获取 git 分支
    git_branch = None
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_branch = result.stdout.strip()
    except Exception:
        pass

    default_display_name = f"{user_name} @ {environment_os}"
    if git_branch:
        default_display_name += f" ({git_branch})"

    new_account = RunAccount(
        account_display_name=default_display_name,
        user_name=user_name,
        environment_os=environment_os,
        git_branch_name=git_branch,
        is_active=True,
    )

    db_session.add(new_account)
    db_session.commit()
    db_session.refresh(new_account)

    logger.info(f"Auto-created default RunAccount: {new_account.id[:8]}...")
    return new_account
