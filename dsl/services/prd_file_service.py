"""Helpers for task-scoped PRD file naming and lookup.

Koda keeps a stable task-id prefix in PRD filenames so the backend can always
locate the current task's document, while still allowing an AI-generated
English slug to describe the requirement semantics.
"""

from __future__ import annotations

from pathlib import Path


def build_task_prd_file_prefix(task_id_str: str) -> str:
    """Build the task-specific PRD filename prefix.

    Args:
        task_id_str: Task UUID string.

    Returns:
        str: Prefix such as ``prd-cf2b9461``.
    """
    return f"prd-{task_id_str[:8]}"


def build_task_prd_output_path_contract(task_id_str: str) -> str:
    """Build the PRD path contract shown to Codex in prompts.

    Args:
        task_id_str: Task UUID string.

    Returns:
        str: Output contract such as
            ``tasks/prd-cf2b9461-<english-requirement-slug>.md``.
    """
    task_prd_file_prefix = build_task_prd_file_prefix(task_id_str)
    return f"tasks/{task_prd_file_prefix}-<english-requirement-slug>.md"


def list_task_prd_file_paths(worktree_dir_path: Path, task_id_str: str) -> list[Path]:
    """List candidate PRD files for one task, newest semantic filenames first.

    Args:
        worktree_dir_path: Task worktree root directory.
        task_id_str: Task UUID string.

    Returns:
        list[Path]: Matching PRD file paths sorted so semantic slug filenames are
            preferred over the legacy fixed filename, and newer files win within
            the same class.
    """
    tasks_directory_path = worktree_dir_path / "tasks"
    if not tasks_directory_path.exists():
        return []

    task_prd_file_prefix = build_task_prd_file_prefix(task_id_str)
    matching_prd_file_path_list = list(
        tasks_directory_path.glob(f"{task_prd_file_prefix}*.md")
    )

    def _sort_key(task_prd_file_path: Path) -> tuple[int, float, str]:
        task_prd_stem = task_prd_file_path.stem
        has_semantic_slug = task_prd_stem != task_prd_file_prefix
        try:
            last_modified_timestamp = task_prd_file_path.stat().st_mtime
        except OSError:
            last_modified_timestamp = -1.0
        return (
            1 if has_semantic_slug else 0,
            last_modified_timestamp,
            task_prd_file_path.name,
        )

    return sorted(
        matching_prd_file_path_list,
        key=_sort_key,
        reverse=True,
    )


def find_task_prd_file_path(worktree_dir_path: Path, task_id_str: str) -> Path | None:
    """Resolve the best PRD file path for a task.

    Args:
        worktree_dir_path: Task worktree root directory.
        task_id_str: Task UUID string.

    Returns:
        Path | None: The best matching PRD file path, or ``None`` when absent.
    """
    matching_prd_file_path_list = list_task_prd_file_paths(
        worktree_dir_path=worktree_dir_path,
        task_id_str=task_id_str,
    )
    if not matching_prd_file_path_list:
        return None

    return matching_prd_file_path_list[0]
