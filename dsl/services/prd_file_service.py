"""Helpers for task-scoped PRD file naming and lookup.

Koda's canonical PRD filename contract is ``tasks/prd-<task_id[:8]>.md``.
Prefix-based lookup remains only as a backwards-compatible fallback for older
slugged filenames that still start with the same stable task prefix.
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
        str: Output contract such as ``tasks/prd-cf2b9461.md``.
    """
    task_prd_file_prefix = build_task_prd_file_prefix(task_id_str)
    return f"tasks/{task_prd_file_prefix}.md"


def list_task_prd_file_paths(worktree_dir_path: Path, task_id_str: str) -> list[Path]:
    """List candidate PRD files for one task, canonical filename first.

    Args:
        worktree_dir_path: Task worktree root directory.
        task_id_str: Task UUID string.

    Returns:
        list[Path]: Matching PRD file paths sorted so the canonical fixed
            filename wins first, and legacy slugged filenames remain as
            backwards-compatible fallbacks ordered by recency.
    """
    tasks_directory_path = worktree_dir_path / "tasks"
    if not tasks_directory_path.exists():
        return []

    task_prd_file_prefix = build_task_prd_file_prefix(task_id_str)
    canonical_task_prd_filename = f"{task_prd_file_prefix}.md"
    matching_prd_file_path_list = list(
        tasks_directory_path.glob(f"{task_prd_file_prefix}*.md")
    )

    def _sort_key(task_prd_file_path: Path) -> tuple[int, float, str]:
        is_canonical_filename = task_prd_file_path.name == canonical_task_prd_filename
        try:
            last_modified_timestamp = task_prd_file_path.stat().st_mtime
        except OSError:
            last_modified_timestamp = -1.0
        return (
            1 if is_canonical_filename else 0,
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
