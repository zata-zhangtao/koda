"""Worktree resource scanning, policy resolution, and materialization."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from backend.dsl.worktree_resources.schemas import (
    ProjectWorktreeResourcePolicySchema,
    ProjectWorktreeResourceRuleSchema,
    WorktreeResourceCandidateListSchema,
    WorktreeResourceCandidateSchema,
    WorktreeResourceGitState,
    WorktreeResourceMaterialization,
    WorktreeResourcePolicyConfirmation,
)

_RUNTIME_DIR_NAME_SET: set[str] = {
    ".venv",
    "node_modules",
    ".uv-cache",
    "dist",
    "build",
    "site",
    "logs",
    "log",
    "cache",
    "uploads",
    "data",
    "storage",
}
_NO_SHOW_DIR_NAME_SET: set[str] = {
    "__pycache__",
    ".angular",
    ".cache",
    ".hypothesis",
    ".mypy_cache",
    ".next",
    ".nox",
    ".nuxt",
    ".nyc_output",
    ".parcel-cache",
    ".pyre",
    ".pytest_cache",
    ".pytype",
    ".ruff_cache",
    ".svelte-kit",
    ".tox",
    ".turbo",
    ".uv-cache",
    ".vite",
    "build",
    "cache",
    "coverage",
    "dist",
    "htmlcov",
    "log",
    "logs",
    "site",
}
_NO_SHOW_FILE_NAME_SET: set[str] = {
    ".DS_Store",
    ".coverage",
    "coverage.json",
    "coverage.xml",
    "lcov.info",
    "pytestdebug.log",
}
_NO_SHOW_FILE_SUFFIX_SET: set[str] = {
    ".cache",
    ".log",
    ".pyc",
    ".pyd",
    ".pyo",
    ".tmp",
}
_COPY_FILE_SUFFIX_SET: set[str] = {".env", ".pem", ".key"}
_LINK_FILE_SUFFIX_SET: set[str] = {".db", ".sqlite", ".sqlite3"}
_SKIP_FILE_SUFFIX_SET: set[str] = {".log", ".tmp", ".cache"}
_SKIP_EXACT_PATH_SET: set[str] = {".DS_Store"}


@dataclass(frozen=True, slots=True)
class _CandidateDecision:
    """Intermediate candidate classification."""

    resource_kind: str
    materialization: WorktreeResourceMaterialization
    warning_codes: list[str]
    warning_text: str | None
    is_directory: bool


@dataclass(frozen=True, slots=True)
class _CollectedResourceCandidate:
    """Discovered candidate path with Git state and filesystem kind."""

    relative_path: str
    git_state: WorktreeResourceGitState
    is_directory: bool


_GIT_STATE_PRIORITY: dict[WorktreeResourceGitState, int] = {
    WorktreeResourceGitState.TRACKED: 3,
    WorktreeResourceGitState.IGNORED: 2,
    WorktreeResourceGitState.UNTRACKED: 1,
}


def _normalize_repo_relative_path(raw_relative_path_str: str) -> str:
    """Normalize one Git path into a safe repo-relative POSIX path."""

    normalized_path_str = raw_relative_path_str.strip().replace("\\", "/")
    normalized_path = PurePosixPath(normalized_path_str)
    if normalized_path.is_absolute():
        raise ValueError(f"Invalid repo-relative path: {raw_relative_path_str}")
    normalized_relative_path_str = normalized_path.as_posix().lstrip("/")
    if not normalized_relative_path_str or normalized_relative_path_str in {".", ".."}:
        raise ValueError(f"Invalid repo-relative path: {raw_relative_path_str}")
    if any(path_part in {"", ".", ".."} for path_part in normalized_path.parts):
        raise ValueError(f"Invalid repo-relative path: {raw_relative_path_str}")
    return normalized_relative_path_str


def _run_git_lines(repo_root_path: Path, git_argument_list: list[str]) -> list[str]:
    """Run a Git command and return stripped stdout lines."""

    completed_process = subprocess.run(
        ["git", "-C", str(repo_root_path), *git_argument_list],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [
        raw_line.strip()
        for raw_line in completed_process.stdout.splitlines()
        if raw_line.strip()
    ]


def _collapse_candidate_path(raw_relative_path_str: str) -> str:
    """Collapse file paths into stable runtime resource roots when appropriate."""

    normalized_relative_path_str = _normalize_repo_relative_path(raw_relative_path_str)
    path_part_list = PurePosixPath(normalized_relative_path_str).parts
    if not path_part_list:
        return normalized_relative_path_str

    first_part_str = path_part_list[0]
    if first_part_str in _RUNTIME_DIR_NAME_SET:
        return first_part_str

    if len(path_part_list) > 1 and path_part_list[1] in _RUNTIME_DIR_NAME_SET:
        return "/".join(path_part_list[:2])

    return normalized_relative_path_str


def _should_hide_generated_candidate(raw_relative_path_str: str) -> bool:
    """Return whether a generated artifact should stay out of the chooser."""

    normalized_relative_path_str = _normalize_repo_relative_path(raw_relative_path_str)
    candidate_path = PurePosixPath(normalized_relative_path_str)
    path_part_set = set(candidate_path.parts)
    if path_part_set.intersection(_NO_SHOW_DIR_NAME_SET):
        return True

    candidate_name_str = candidate_path.name
    candidate_name_lower_str = candidate_name_str.lower()
    if candidate_name_str in _NO_SHOW_FILE_NAME_SET:
        return True
    if candidate_name_str.startswith(".coverage."):
        return True
    return candidate_name_lower_str.endswith(tuple(_NO_SHOW_FILE_SUFFIX_SET))


def _classify_candidate(
    relative_path_str: str,
    git_state: WorktreeResourceGitState,
    is_directory: bool,
) -> _CandidateDecision:
    """Classify one candidate into a default materialization action."""

    if git_state == WorktreeResourceGitState.TRACKED:
        return _CandidateDecision(
            resource_kind="tracked",
            materialization=WorktreeResourceMaterialization.GIT_MANAGED_COPY,
            warning_codes=[],
            warning_text=None,
            is_directory=is_directory,
        )

    candidate_path = PurePosixPath(relative_path_str)
    candidate_name_str = candidate_path.name
    candidate_suffix_str = candidate_path.suffix.lower()
    first_part_str = (
        candidate_path.parts[0] if candidate_path.parts else candidate_name_str
    )

    if relative_path_str in _SKIP_EXACT_PATH_SET:
        return _CandidateDecision(
            resource_kind="system",
            materialization=WorktreeResourceMaterialization.SKIP,
            warning_codes=["system-file"],
            warning_text="Skip OS metadata files.",
            is_directory=is_directory,
        )

    if first_part_str in {".venv", "node_modules"} or relative_path_str in {
        ".venv",
        "node_modules",
    }:
        return _CandidateDecision(
            resource_kind="dependency",
            materialization=WorktreeResourceMaterialization.LINK,
            warning_codes=["large-shared-dependency"],
            warning_text="Shared dependency directory.",
            is_directory=True,
        )

    if first_part_str in {"uploads", "data", "storage"}:
        return _CandidateDecision(
            resource_kind="mutable-data",
            materialization=WorktreeResourceMaterialization.LINK,
            warning_codes=["shared-mutable"],
            warning_text="Shared mutable runtime data.",
            is_directory=True,
        )

    if first_part_str in {"logs", "log", "cache", ".uv-cache", "dist", "build", "site"}:
        return _CandidateDecision(
            resource_kind="generated-output",
            materialization=WorktreeResourceMaterialization.SKIP,
            warning_codes=["generated-output"],
            warning_text="Generated output is skipped.",
            is_directory=True,
        )

    if candidate_name_str.startswith(".env") or candidate_suffix_str in {
        ".pem",
        ".key",
    }:
        return _CandidateDecision(
            resource_kind="secret",
            materialization=WorktreeResourceMaterialization.COPY,
            warning_codes=["secret"],
            warning_text="Sensitive config is copied into the task worktree.",
            is_directory=False,
        )

    if candidate_suffix_str in {".db", ".sqlite", ".sqlite3"}:
        return _CandidateDecision(
            resource_kind="database",
            materialization=WorktreeResourceMaterialization.LINK,
            warning_codes=["shared-mutable"],
            warning_text="Local database should stay shared between worktrees.",
            is_directory=False,
        )

    if candidate_suffix_str in _SKIP_FILE_SUFFIX_SET:
        return _CandidateDecision(
            resource_kind="generated-output",
            materialization=WorktreeResourceMaterialization.SKIP,
            warning_codes=["generated-output"],
            warning_text="Generated output is skipped.",
            is_directory=False,
        )

    if is_directory and git_state in {
        WorktreeResourceGitState.UNTRACKED,
        WorktreeResourceGitState.IGNORED,
    }:
        return _CandidateDecision(
            resource_kind="manual-review-directory",
            materialization=WorktreeResourceMaterialization.SKIP,
            warning_codes=["manual-review-required"],
            warning_text="Unknown runtime directory candidate; review manually.",
            is_directory=True,
        )

    if git_state in {
        WorktreeResourceGitState.UNTRACKED,
        WorktreeResourceGitState.IGNORED,
    }:
        return _CandidateDecision(
            resource_kind="manual-review",
            materialization=WorktreeResourceMaterialization.SKIP,
            warning_codes=["manual-review-required"],
            warning_text="Unknown runtime resource candidate; review manually.",
            is_directory=False,
        )

    return _CandidateDecision(
        resource_kind="runtime",
        materialization=WorktreeResourceMaterialization.GIT_MANAGED_COPY,
        warning_codes=[],
        warning_text=None,
        is_directory=False,
    )


def _build_candidate_schema(
    repo_root_path: Path,
    relative_path_str: str,
    git_state: WorktreeResourceGitState,
    is_directory: bool,
    draft_policy: ProjectWorktreeResourcePolicySchema | None,
) -> WorktreeResourceCandidateSchema:
    """Build a preview candidate schema from one discovered path."""

    normalized_relative_path_str = (
        _normalize_repo_relative_path(relative_path_str)
        if git_state == WorktreeResourceGitState.TRACKED
        else _collapse_candidate_path(relative_path_str)
    )
    source_path = repo_root_path / normalized_relative_path_str
    is_directory_bool = is_directory or source_path.is_dir()
    classification_result = _classify_candidate(
        normalized_relative_path_str,
        git_state,
        is_directory_bool,
    )
    selected_materialization = classification_result.materialization
    if draft_policy is not None:
        for policy_rule in draft_policy.rules:
            if policy_rule.relative_path == normalized_relative_path_str:
                selected_materialization = policy_rule.materialization
                break

    return WorktreeResourceCandidateSchema(
        relative_path=normalized_relative_path_str,
        git_state=git_state,
        resource_kind=classification_result.resource_kind,
        materialization=selected_materialization,
        warning_codes=classification_result.warning_codes,
        warning_text=classification_result.warning_text,
        is_directory=classification_result.is_directory,
    )


def _build_policy_rule_from_candidate(
    candidate_schema: WorktreeResourceCandidateSchema,
) -> ProjectWorktreeResourceRuleSchema:
    """Convert one candidate into a persisted policy rule."""

    return ProjectWorktreeResourceRuleSchema(
        relative_path=candidate_schema.relative_path,
        include=True,
        materialization=candidate_schema.materialization,
        resource_kind=candidate_schema.resource_kind,
        git_state=candidate_schema.git_state,
        required="secret" in candidate_schema.warning_codes,
        is_directory=candidate_schema.is_directory,
        note=candidate_schema.warning_text,
    )


def _record_resource_candidate(
    candidate_state_map: dict[str, _CollectedResourceCandidate],
    *,
    relative_path_str: str,
    git_state: WorktreeResourceGitState,
    is_directory: bool,
) -> None:
    """Record one candidate while preserving the strongest Git-state signal."""

    normalized_relative_path_str = _normalize_repo_relative_path(relative_path_str)
    existing_candidate = candidate_state_map.get(normalized_relative_path_str)
    if existing_candidate is None:
        candidate_state_map[normalized_relative_path_str] = _CollectedResourceCandidate(
            relative_path=normalized_relative_path_str,
            git_state=git_state,
            is_directory=is_directory,
        )
        return

    existing_priority_int = _GIT_STATE_PRIORITY[existing_candidate.git_state]
    incoming_priority_int = _GIT_STATE_PRIORITY[git_state]
    if incoming_priority_int > existing_priority_int:
        candidate_state_map[normalized_relative_path_str] = _CollectedResourceCandidate(
            relative_path=normalized_relative_path_str,
            git_state=git_state,
            is_directory=is_directory or existing_candidate.is_directory,
        )
        return

    if incoming_priority_int == existing_priority_int and (
        is_directory and not existing_candidate.is_directory
    ):
        candidate_state_map[normalized_relative_path_str] = _CollectedResourceCandidate(
            relative_path=normalized_relative_path_str,
            git_state=existing_candidate.git_state,
            is_directory=True,
        )


def _record_parent_directory_candidates(
    candidate_state_map: dict[str, _CollectedResourceCandidate],
    *,
    repo_root_path: Path,
    relative_path_str: str,
    git_state: WorktreeResourceGitState,
) -> None:
    """Record real parent directories so folders can be configured directly."""

    normalized_relative_path_str = _normalize_repo_relative_path(relative_path_str)
    path_part_list = PurePosixPath(normalized_relative_path_str).parts
    if len(path_part_list) <= 1:
        return

    parent_part_list: list[str] = []
    for path_part_str in path_part_list[:-1]:
        parent_part_list.append(path_part_str)
        parent_relative_path_str = "/".join(parent_part_list)
        parent_source_path = repo_root_path / parent_relative_path_str
        if not parent_source_path.is_dir():
            continue
        _record_resource_candidate(
            candidate_state_map,
            relative_path_str=parent_relative_path_str,
            git_state=git_state,
            is_directory=True,
        )


def _collect_repo_resource_candidates(
    repo_root_path: Path,
) -> list[_CollectedResourceCandidate]:
    """Collect unique untracked and ignored runtime resource paths."""

    candidate_state_map: dict[str, _CollectedResourceCandidate] = {}

    for raw_relative_path_str in _run_git_lines(
        repo_root_path,
        ["ls-files", "--others", "--exclude-standard"],
    ):
        if _should_hide_generated_candidate(raw_relative_path_str):
            continue
        collapsed_relative_path_str = _collapse_candidate_path(raw_relative_path_str)
        collapsed_source_path = repo_root_path / collapsed_relative_path_str
        _record_resource_candidate(
            candidate_state_map,
            relative_path_str=collapsed_relative_path_str,
            git_state=WorktreeResourceGitState.UNTRACKED,
            is_directory=collapsed_source_path.is_dir(),
        )
        _record_parent_directory_candidates(
            candidate_state_map,
            repo_root_path=repo_root_path,
            relative_path_str=collapsed_relative_path_str,
            git_state=WorktreeResourceGitState.UNTRACKED,
        )

    for raw_relative_path_str in _run_git_lines(
        repo_root_path,
        ["ls-files", "--others", "--ignored", "--exclude-standard"],
    ):
        if _should_hide_generated_candidate(raw_relative_path_str):
            continue
        collapsed_relative_path_str = _collapse_candidate_path(raw_relative_path_str)
        collapsed_source_path = repo_root_path / collapsed_relative_path_str
        _record_resource_candidate(
            candidate_state_map,
            relative_path_str=collapsed_relative_path_str,
            git_state=WorktreeResourceGitState.IGNORED,
            is_directory=collapsed_source_path.is_dir(),
        )
        _record_parent_directory_candidates(
            candidate_state_map,
            repo_root_path=repo_root_path,
            relative_path_str=collapsed_relative_path_str,
            git_state=WorktreeResourceGitState.IGNORED,
        )

    return sorted(
        candidate_state_map.values(),
        key=lambda candidate: candidate.relative_path,
    )


def build_default_project_worktree_resource_policy(
    repo_root_path: Path,
) -> ProjectWorktreeResourcePolicySchema:
    """Build the default confirmed policy for one repo."""

    candidate_schema_list = preview_project_worktree_resource_candidates(
        repo_root_path=repo_root_path,
        draft_policy=None,
    ).candidates
    rule_list = [
        _build_policy_rule_from_candidate(candidate_schema)
        for candidate_schema in candidate_schema_list
    ]
    return ProjectWorktreeResourcePolicySchema(
        confirmation_status=WorktreeResourcePolicyConfirmation.ACCEPTED_DEFAULT,
        rules=rule_list,
    )


def preview_project_worktree_resource_candidates(
    repo_root_path: Path,
    draft_policy: ProjectWorktreeResourcePolicySchema | None = None,
) -> WorktreeResourceCandidateListSchema:
    """Preview repo-local runtime resource candidates."""

    candidate_schema_list = [
        _build_candidate_schema(
            repo_root_path,
            collected_candidate.relative_path,
            collected_candidate.git_state,
            collected_candidate.is_directory,
            draft_policy,
        )
        for collected_candidate in _collect_repo_resource_candidates(repo_root_path)
    ]
    if draft_policy is None:
        policy_note_text = None
        is_policy_ready_bool = False
    else:
        is_policy_ready_bool = (
            draft_policy.confirmation_status
            != WorktreeResourcePolicyConfirmation.DEFERRED
        )
        policy_note_text = (
            "Project policy is deferred and must be confirmed before task start."
            if draft_policy.confirmation_status
            == WorktreeResourcePolicyConfirmation.DEFERRED
            else None
        )

    return WorktreeResourceCandidateListSchema(
        repo_path=str(repo_root_path),
        is_policy_ready=is_policy_ready_bool,
        policy_note=policy_note_text,
        candidates=candidate_schema_list,
    )


def parse_project_worktree_resource_policy(
    raw_policy_json_str: str | None,
) -> ProjectWorktreeResourcePolicySchema | None:
    """Parse a stored policy JSON string."""

    if raw_policy_json_str is None:
        return None
    normalized_policy_json_str = raw_policy_json_str.strip()
    if not normalized_policy_json_str:
        return None
    try:
        return ProjectWorktreeResourcePolicySchema.model_validate_json(
            normalized_policy_json_str
        )
    except Exception:
        return None


def resolve_project_worktree_resource_policy(
    project_obj: object,
) -> ProjectWorktreeResourcePolicySchema | None:
    """Resolve a project's stored policy into a typed schema."""

    raw_policy_json_str = getattr(project_obj, "worktree_resource_policy_json", None)
    return parse_project_worktree_resource_policy(raw_policy_json_str)


def build_project_worktree_resource_policy_note(
    project_obj: object,
) -> tuple[bool, str | None, ProjectWorktreeResourcePolicySchema | None]:
    """Return policy readiness, a note, and the parsed policy for one project."""

    repo_path_str = getattr(project_obj, "repo_path", "")
    raw_policy_json_str = getattr(project_obj, "worktree_resource_policy_json", None)
    parsed_policy = resolve_project_worktree_resource_policy(project_obj)
    if parsed_policy is None:
        if raw_policy_json_str:
            return (
                False,
                "Project worktree resource policy JSON could not be parsed.",
                None,
            )
        repo_path_obj = Path(repo_path_str).expanduser()
        if repo_path_obj.exists() and (repo_path_obj / ".git").exists():
            inferred_draft_policy = build_default_project_worktree_resource_policy(
                repo_path_obj
            ).model_copy(
                update={
                    "confirmation_status": (WorktreeResourcePolicyConfirmation.DEFERRED)
                }
            )
            return (
                False,
                "Legacy project without stored worktree resource policy; confirm Worktree Resources before starting a task.",
                inferred_draft_policy,
            )
        return False, "Project worktree resource policy is not configured yet.", None
    if parsed_policy.confirmation_status == WorktreeResourcePolicyConfirmation.DEFERRED:
        return (
            False,
            "Confirm Worktree Resources in Project settings before starting a task.",
            parsed_policy,
        )
    return True, None, parsed_policy


def _ensure_parent_directory(target_path: Path) -> None:
    """Create the parent directory for a materialized resource."""

    target_path.parent.mkdir(parents=True, exist_ok=True)


def _copy_or_link_file(
    source_path: Path,
    target_path: Path,
    materialization: WorktreeResourceMaterialization,
) -> None:
    """Copy or link a file into the worktree."""

    _ensure_parent_directory(target_path)
    if materialization == WorktreeResourceMaterialization.COPY:
        shutil.copy2(source_path, target_path)
        return
    if materialization == WorktreeResourceMaterialization.LINK:
        os.symlink(source_path, target_path)
        return
    raise ValueError(f"Unsupported file materialization: {materialization}")


def _copy_or_link_directory(
    source_path: Path,
    target_path: Path,
    materialization: WorktreeResourceMaterialization,
) -> None:
    """Copy or link a directory into the worktree."""

    _ensure_parent_directory(target_path)
    if materialization == WorktreeResourceMaterialization.COPY:
        shutil.copytree(source_path, target_path, dirs_exist_ok=True)
        return
    if materialization == WorktreeResourceMaterialization.LINK:
        os.symlink(source_path, target_path, target_is_directory=True)
        return
    raise ValueError(f"Unsupported directory materialization: {materialization}")


def _ensure_resolved_child_path(
    *,
    root_path: Path,
    child_path: Path,
    path_label_str: str,
) -> Path:
    """Resolve a child path and ensure it remains within the root.

    Args:
        root_path: Expected root directory.
        child_path: Candidate child path.
        path_label_str: Label used in validation errors.

    Returns:
        Path: Resolved child path.

    Raises:
        ValueError: Raised when the resolved child escapes the expected root.
    """

    resolved_root_path = root_path.resolve()
    resolved_child_path = child_path.resolve(strict=False)
    try:
        resolved_child_path.relative_to(resolved_root_path)
    except ValueError as path_error:
        raise ValueError(
            f"Unsafe worktree resource {path_label_str}: path escapes expected root."
        ) from path_error
    return resolved_child_path


def _ensure_directory_copy_sources_remain_inside_root(
    *,
    root_path: Path,
    directory_path: Path,
    path_label_str: str,
) -> None:
    """Ensure copied directory symlinks do not resolve outside the source root."""

    for current_directory_str, directory_name_list, file_name_list in os.walk(
        directory_path,
        followlinks=False,
    ):
        current_directory_path = Path(current_directory_str)
        for entry_name_str in [*directory_name_list, *file_name_list]:
            entry_path = current_directory_path / entry_name_str
            if not entry_path.is_symlink():
                continue
            entry_relative_path = entry_path.relative_to(directory_path)
            _ensure_resolved_child_path(
                root_path=root_path,
                child_path=entry_path.resolve(strict=True),
                path_label_str=f"{path_label_str}/{entry_relative_path.as_posix()}",
            )


def _should_materialize_policy_rule(
    policy_rule: ProjectWorktreeResourceRuleSchema,
) -> bool:
    """Return whether a policy rule creates a target in the worktree."""

    return policy_rule.include and policy_rule.materialization not in {
        WorktreeResourceMaterialization.SKIP,
        WorktreeResourceMaterialization.GIT_MANAGED_COPY,
    }


def _has_materialized_directory_ancestor(
    *,
    relative_path_str: str,
    materialized_directory_path_set: set[str],
) -> bool:
    """Return whether a path is covered by an already materialized directory."""

    relative_path = PurePosixPath(relative_path_str)
    for materialized_directory_path_str in materialized_directory_path_set:
        materialized_directory_path = PurePosixPath(materialized_directory_path_str)
        if relative_path == materialized_directory_path:
            continue
        try:
            relative_path.relative_to(materialized_directory_path)
        except ValueError:
            continue
        return True
    return False


def _ensure_required_policy_sources_exist(
    *,
    repo_root_path: Path,
    project_policy: ProjectWorktreeResourcePolicySchema,
) -> None:
    """Validate required materialized sources before mutating the worktree."""

    for policy_rule in project_policy.rules:
        if not _should_materialize_policy_rule(policy_rule) or not policy_rule.required:
            continue

        source_path = repo_root_path / policy_rule.relative_path
        _ensure_resolved_child_path(
            root_path=repo_root_path,
            child_path=source_path,
            path_label_str=policy_rule.relative_path,
        )
        if not source_path.exists():
            raise ValueError(
                f"Cannot materialize required resource {policy_rule.relative_path}: source is missing."
            )
        _ensure_resolved_child_path(
            root_path=repo_root_path,
            child_path=source_path.resolve(strict=True),
            path_label_str=policy_rule.relative_path,
        )


def materialize_project_worktree_resources(
    repo_root_path: Path,
    worktree_root_path: Path,
    project_policy: ProjectWorktreeResourcePolicySchema,
) -> None:
    """Materialize runtime resources into a task worktree."""

    _ensure_required_policy_sources_exist(
        repo_root_path=repo_root_path,
        project_policy=project_policy,
    )
    materialized_directory_path_set: set[str] = set()
    sorted_policy_rule_list = sorted(
        project_policy.rules,
        key=lambda rule: (
            len(PurePosixPath(rule.relative_path).parts),
            rule.relative_path,
        ),
    )

    for policy_rule in sorted_policy_rule_list:
        if not _should_materialize_policy_rule(policy_rule):
            continue
        if _has_materialized_directory_ancestor(
            relative_path_str=policy_rule.relative_path,
            materialized_directory_path_set=materialized_directory_path_set,
        ):
            continue

        source_path = repo_root_path / policy_rule.relative_path
        target_path = worktree_root_path / policy_rule.relative_path
        _ensure_resolved_child_path(
            root_path=repo_root_path,
            child_path=source_path,
            path_label_str=policy_rule.relative_path,
        )
        _ensure_resolved_child_path(
            root_path=worktree_root_path,
            child_path=target_path.parent,
            path_label_str=policy_rule.relative_path,
        )
        if not source_path.exists():
            if policy_rule.required:
                raise ValueError(
                    f"Cannot materialize required resource {policy_rule.relative_path}: source is missing."
                )
            continue
        _ensure_resolved_child_path(
            root_path=repo_root_path,
            child_path=source_path.resolve(strict=True),
            path_label_str=policy_rule.relative_path,
        )
        if target_path.exists() or target_path.is_symlink():
            if target_path.resolve() == source_path.resolve():
                continue
            raise ValueError(
                f"Cannot materialize {policy_rule.relative_path}: target already exists."
            )

        if source_path.is_dir():
            if policy_rule.materialization == WorktreeResourceMaterialization.COPY:
                _ensure_directory_copy_sources_remain_inside_root(
                    root_path=repo_root_path,
                    directory_path=source_path,
                    path_label_str=policy_rule.relative_path,
                )
            _copy_or_link_directory(
                source_path=source_path,
                target_path=target_path,
                materialization=policy_rule.materialization,
            )
            materialized_directory_path_set.add(policy_rule.relative_path)
            continue

        _copy_or_link_file(
            source_path=source_path,
            target_path=target_path,
            materialization=policy_rule.materialization,
        )
