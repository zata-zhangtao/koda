"""Tests for worktree local resource policy helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.dsl.worktree_resources import (
    ProjectWorktreeResourcePolicySchema,
    ProjectWorktreeResourceRuleSchema,
    WorktreeResourceGitState,
    WorktreeResourceMaterialization,
    WorktreeResourcePolicyConfirmation,
    build_default_project_worktree_resource_policy,
    materialize_project_worktree_resources,
    preview_project_worktree_resource_candidates,
)


def _run_git_command(repo_root_path: Path, git_argument_list: list[str]) -> str:
    """Run a Git command inside a temporary repository."""

    completed_process = subprocess.run(
        ["git", "-C", str(repo_root_path), *git_argument_list],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed_process.stdout.strip()


def _create_git_repo(repo_root_path: Path) -> Path:
    """Create a real Git repository with one tracked file and ignored resources."""

    repo_root_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(repo_root_path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    _run_git_command(repo_root_path, ["config", "user.email", "tester@example.com"])
    _run_git_command(repo_root_path, ["config", "user.name", "Tester"])
    (repo_root_path / "README.md").write_text("hello\n", encoding="utf-8")
    (repo_root_path / ".gitignore").write_text(
        ".env\nnode_modules/\ndata/\nlogs/\n",
        encoding="utf-8",
    )
    _run_git_command(repo_root_path, ["add", "README.md", ".gitignore"])
    _run_git_command(repo_root_path, ["commit", "-m", "init"])
    return repo_root_path


def test_preview_project_worktree_resource_candidates_classifies_runtime_resources(
    tmp_path: Path,
) -> None:
    """Preview should surface ignored runtime resources with sensible defaults."""

    repo_root_path = _create_git_repo(tmp_path / "demo-repo")
    (repo_root_path / ".env").write_text("TOKEN=demo\n", encoding="utf-8")
    (repo_root_path / "data").mkdir()
    (repo_root_path / "data" / "app.sqlite").write_text("db", encoding="utf-8")
    (repo_root_path / "node_modules").mkdir()
    (repo_root_path / "node_modules" / "pkg.txt").write_text(
        "deps",
        encoding="utf-8",
    )

    preview_result = preview_project_worktree_resource_candidates(repo_root_path)

    preview_path_list = [
        candidate.relative_path for candidate in preview_result.candidates
    ]
    assert "README.md" not in preview_path_list
    assert ".env" in preview_path_list
    assert "data" in preview_path_list
    assert "node_modules" in preview_path_list
    assert preview_result.is_policy_ready is False

    env_candidate = next(
        candidate
        for candidate in preview_result.candidates
        if candidate.relative_path == ".env"
    )
    data_candidate = next(
        candidate
        for candidate in preview_result.candidates
        if candidate.relative_path == "data"
    )
    node_modules_candidate = next(
        candidate
        for candidate in preview_result.candidates
        if candidate.relative_path == "node_modules"
    )

    assert env_candidate.materialization == WorktreeResourceMaterialization.COPY
    assert data_candidate.materialization == WorktreeResourceMaterialization.LINK
    assert (
        node_modules_candidate.materialization == WorktreeResourceMaterialization.LINK
    )


def test_preview_project_worktree_resource_candidates_surfaces_untracked_folders(
    tmp_path: Path,
) -> None:
    """Preview should make ordinary local folders directly configurable."""

    repo_root_path = _create_git_repo(tmp_path / "folder-preview-repo")
    (repo_root_path / "fixtures").mkdir()
    (repo_root_path / "fixtures" / "sample.json").write_text(
        '{"ok": true}\n',
        encoding="utf-8",
    )

    preview_result = preview_project_worktree_resource_candidates(repo_root_path)

    folder_candidate = next(
        candidate
        for candidate in preview_result.candidates
        if candidate.relative_path == "fixtures"
    )
    file_candidate = next(
        candidate
        for candidate in preview_result.candidates
        if candidate.relative_path == "fixtures/sample.json"
    )

    assert folder_candidate.git_state == WorktreeResourceGitState.UNTRACKED
    assert folder_candidate.is_directory is True
    assert folder_candidate.resource_kind == "manual-review-directory"
    assert folder_candidate.materialization == WorktreeResourceMaterialization.SKIP
    assert file_candidate.is_directory is False


def test_preview_project_worktree_resource_candidates_hides_generated_artifacts(
    tmp_path: Path,
) -> None:
    """Preview should omit caches, bytecode, logs, and coverage outputs."""

    repo_root_path = _create_git_repo(tmp_path / "generated-artifacts-repo")
    generated_artifact_path_list = [
        repo_root_path / "__pycache__" / "module.cpython-313.pyc",
        repo_root_path / ".pytest_cache" / "README.md",
        repo_root_path / ".mypy_cache" / "3.13" / "module.meta.json",
        repo_root_path / ".ruff_cache" / "content",
        repo_root_path / "htmlcov" / "index.html",
        repo_root_path / "dist" / "bundle.js",
        repo_root_path / "logs" / "app.log",
        repo_root_path / ".coverage",
        repo_root_path / "coverage.xml",
    ]
    for generated_artifact_path in generated_artifact_path_list:
        generated_artifact_path.parent.mkdir(parents=True, exist_ok=True)
        generated_artifact_path.write_text("generated\n", encoding="utf-8")
    (repo_root_path / ".env.local").write_text("TOKEN=demo\n", encoding="utf-8")

    preview_result = preview_project_worktree_resource_candidates(repo_root_path)

    preview_path_list = [
        candidate.relative_path for candidate in preview_result.candidates
    ]
    assert ".env.local" in preview_path_list
    assert not any("__pycache__" in path for path in preview_path_list)
    assert not any(".pytest_cache" in path for path in preview_path_list)
    assert not any(".mypy_cache" in path for path in preview_path_list)
    assert not any(".ruff_cache" in path for path in preview_path_list)
    assert "htmlcov" not in preview_path_list
    assert "dist" not in preview_path_list
    assert "logs" not in preview_path_list
    assert ".coverage" not in preview_path_list
    assert "coverage.xml" not in preview_path_list


def test_materialize_project_worktree_resources_copies_and_links_resources(
    tmp_path: Path,
) -> None:
    """Materialization should copy secret files and link shared runtime data."""

    repo_root_path = _create_git_repo(tmp_path / "materialized-repo")
    (repo_root_path / ".env").write_text("TOKEN=demo\n", encoding="utf-8")
    (repo_root_path / "data").mkdir()
    (repo_root_path / "data" / "app.sqlite").write_text("db", encoding="utf-8")
    (repo_root_path / "node_modules").mkdir()
    (repo_root_path / "node_modules" / "pkg.txt").write_text(
        "deps",
        encoding="utf-8",
    )

    policy_schema = build_default_project_worktree_resource_policy(repo_root_path)
    assert policy_schema.confirmation_status == (
        WorktreeResourcePolicyConfirmation.ACCEPTED_DEFAULT
    )

    worktree_root_path = tmp_path / "worktree"
    worktree_root_path.mkdir()

    materialize_project_worktree_resources(
        repo_root_path=repo_root_path,
        worktree_root_path=worktree_root_path,
        project_policy=policy_schema,
    )

    copied_env_path = worktree_root_path / ".env"
    linked_data_path = worktree_root_path / "data"
    linked_node_modules_path = worktree_root_path / "node_modules"

    assert copied_env_path.read_text(encoding="utf-8") == "TOKEN=demo\n"
    assert linked_data_path.is_symlink() is True
    assert linked_data_path.resolve() == (repo_root_path / "data").resolve()
    assert linked_node_modules_path.is_symlink() is True


def test_materialize_project_worktree_resources_folder_rule_covers_children(
    tmp_path: Path,
) -> None:
    """A selected folder rule should materialize the folder before child rules."""

    repo_root_path = _create_git_repo(tmp_path / "folder-materialized-repo")
    (repo_root_path / "fixtures").mkdir()
    (repo_root_path / "fixtures" / "sample.json").write_text(
        '{"ok": true}\n',
        encoding="utf-8",
    )
    policy_schema = ProjectWorktreeResourcePolicySchema(
        confirmation_status=WorktreeResourcePolicyConfirmation.CUSTOMIZED,
        rules=[
            ProjectWorktreeResourceRuleSchema(
                relative_path="fixtures",
                include=True,
                materialization=WorktreeResourceMaterialization.COPY,
                resource_kind="manual-review-directory",
                git_state=WorktreeResourceGitState.UNTRACKED,
                required=False,
                is_directory=True,
            ),
            ProjectWorktreeResourceRuleSchema(
                relative_path="fixtures/sample.json",
                include=True,
                materialization=WorktreeResourceMaterialization.COPY,
                resource_kind="manual-review",
                git_state=WorktreeResourceGitState.UNTRACKED,
                required=False,
                is_directory=False,
            ),
        ],
    )
    worktree_root_path = tmp_path / "worktree"
    worktree_root_path.mkdir()

    materialize_project_worktree_resources(
        repo_root_path=repo_root_path,
        worktree_root_path=worktree_root_path,
        project_policy=policy_schema,
    )

    copied_fixture_file_path = worktree_root_path / "fixtures" / "sample.json"
    assert copied_fixture_file_path.read_text(encoding="utf-8") == '{"ok": true}\n'
    assert copied_fixture_file_path.is_symlink() is False


def test_materialize_project_worktree_resources_skips_git_managed_target(
    tmp_path: Path,
) -> None:
    """Materialization should not collide with paths already checked out by Git."""

    repo_root_path = _create_git_repo(tmp_path / "git-managed-target-repo")
    tracked_claude_settings_path = repo_root_path / ".claude" / "settings.json"
    tracked_claude_settings_path.parent.mkdir()
    tracked_claude_settings_path.write_text('{"permissions": {}}\n', encoding="utf-8")
    _run_git_command(repo_root_path, ["add", ".claude/settings.json"])
    _run_git_command(repo_root_path, ["commit", "-m", "track claude settings"])

    local_claude_runtime_path = repo_root_path / ".claude" / "runtime"
    local_claude_runtime_path.mkdir()
    (local_claude_runtime_path / "local-dev.env").write_text(
        "PORT=3000\n",
        encoding="utf-8",
    )
    worktree_root_path = tmp_path / "task-worktree"
    _run_git_command(
        repo_root_path,
        ["worktree", "add", "-b", "task/git-managed-target", str(worktree_root_path)],
    )
    policy_schema = ProjectWorktreeResourcePolicySchema(
        confirmation_status=WorktreeResourcePolicyConfirmation.CUSTOMIZED,
        rules=[
            ProjectWorktreeResourceRuleSchema(
                relative_path=".claude",
                include=True,
                materialization=WorktreeResourceMaterialization.LINK,
                resource_kind="manual-review-directory",
                git_state=WorktreeResourceGitState.IGNORED,
                required=False,
                is_directory=True,
            ),
            ProjectWorktreeResourceRuleSchema(
                relative_path=".claude/runtime",
                include=True,
                materialization=WorktreeResourceMaterialization.LINK,
                resource_kind="manual-review-directory",
                git_state=WorktreeResourceGitState.IGNORED,
                required=False,
                is_directory=True,
            ),
        ],
    )

    materialize_project_worktree_resources(
        repo_root_path=repo_root_path,
        worktree_root_path=worktree_root_path,
        project_policy=policy_schema,
    )

    worktree_claude_path = worktree_root_path / ".claude"
    worktree_runtime_path = worktree_claude_path / "runtime"
    assert worktree_claude_path.is_symlink() is False
    assert (worktree_claude_path / "settings.json").read_text(
        encoding="utf-8"
    ) == '{"permissions": {}}\n'
    assert worktree_runtime_path.is_symlink() is True
    assert worktree_runtime_path.resolve() == local_claude_runtime_path.resolve()


def test_materialize_project_worktree_resources_folder_rule_keeps_required_checks(
    tmp_path: Path,
) -> None:
    """A folder rule must not hide missing required descendant rules."""

    repo_root_path = _create_git_repo(tmp_path / "folder-required-repo")
    (repo_root_path / "fixtures").mkdir()
    (repo_root_path / "fixtures" / "sample.json").write_text(
        '{"ok": true}\n',
        encoding="utf-8",
    )
    policy_schema = ProjectWorktreeResourcePolicySchema(
        confirmation_status=WorktreeResourcePolicyConfirmation.CUSTOMIZED,
        rules=[
            ProjectWorktreeResourceRuleSchema(
                relative_path="fixtures",
                include=True,
                materialization=WorktreeResourceMaterialization.COPY,
                resource_kind="manual-review-directory",
                git_state=WorktreeResourceGitState.UNTRACKED,
                required=False,
                is_directory=True,
            ),
            ProjectWorktreeResourceRuleSchema(
                relative_path="fixtures/missing.env",
                include=True,
                materialization=WorktreeResourceMaterialization.COPY,
                resource_kind="secret",
                git_state=WorktreeResourceGitState.UNTRACKED,
                required=True,
                is_directory=False,
            ),
        ],
    )
    worktree_root_path = tmp_path / "worktree"
    worktree_root_path.mkdir()

    with pytest.raises(ValueError, match="required resource fixtures/missing.env"):
        materialize_project_worktree_resources(
            repo_root_path=repo_root_path,
            worktree_root_path=worktree_root_path,
            project_policy=policy_schema,
        )

    assert not (worktree_root_path / "fixtures").exists()


def test_materialize_project_worktree_resources_rejects_directory_symlink_escape(
    tmp_path: Path,
) -> None:
    """Copied folder rules should not follow symlinks outside the repository."""

    repo_root_path = _create_git_repo(tmp_path / "folder-symlink-escape-repo")
    outside_secret_path = tmp_path / "outside.txt"
    outside_secret_path.write_text("outside\n", encoding="utf-8")
    (repo_root_path / "fixtures").mkdir()
    try:
        (repo_root_path / "fixtures" / "outside.txt").symlink_to(outside_secret_path)
    except OSError as symlink_error:
        pytest.skip(f"symlink creation is unavailable: {symlink_error}")

    policy_schema = ProjectWorktreeResourcePolicySchema(
        confirmation_status=WorktreeResourcePolicyConfirmation.CUSTOMIZED,
        rules=[
            ProjectWorktreeResourceRuleSchema(
                relative_path="fixtures",
                include=True,
                materialization=WorktreeResourceMaterialization.COPY,
                resource_kind="manual-review-directory",
                git_state=WorktreeResourceGitState.UNTRACKED,
                required=False,
                is_directory=True,
            )
        ],
    )
    worktree_root_path = tmp_path / "worktree"
    worktree_root_path.mkdir()

    with pytest.raises(ValueError, match="escapes expected root"):
        materialize_project_worktree_resources(
            repo_root_path=repo_root_path,
            worktree_root_path=worktree_root_path,
            project_policy=policy_schema,
        )


def test_project_worktree_resource_policy_rejects_unsafe_paths() -> None:
    """Policy validation should reject traversal and absolute rule paths."""

    for unsafe_relative_path in [
        "../secret.env",
        "/tmp/secret.env",
        "C:/Users/demo/.env",
        "safe/../secret.env",
        ".git/config",
        "bad\x00path",
    ]:
        with pytest.raises(ValueError):
            ProjectWorktreeResourcePolicySchema(
                confirmation_status=WorktreeResourcePolicyConfirmation.CUSTOMIZED,
                rules=[
                    ProjectWorktreeResourceRuleSchema(
                        relative_path=unsafe_relative_path,
                        include=True,
                        materialization=WorktreeResourceMaterialization.COPY,
                        resource_kind="secret",
                        git_state=WorktreeResourceGitState.UNTRACKED,
                        required=True,
                    )
                ],
            )


def test_materialize_project_worktree_resources_fails_for_missing_required_source(
    tmp_path: Path,
) -> None:
    """Required policy rules should fail instead of silently skipping."""

    repo_root_path = _create_git_repo(tmp_path / "missing-required-repo")
    (repo_root_path / ".env").write_text("TOKEN=demo\n", encoding="utf-8")
    policy_schema = build_default_project_worktree_resource_policy(repo_root_path)
    (repo_root_path / ".env").unlink()
    worktree_root_path = tmp_path / "worktree"
    worktree_root_path.mkdir()

    with pytest.raises(ValueError, match="required resource .env"):
        materialize_project_worktree_resources(
            repo_root_path=repo_root_path,
            worktree_root_path=worktree_root_path,
            project_policy=policy_schema,
        )


def test_materialize_project_worktree_resources_rejects_source_symlink_escape(
    tmp_path: Path,
) -> None:
    """Source symlinks that resolve outside the repository should be rejected."""

    repo_root_path = _create_git_repo(tmp_path / "symlink-escape-repo")
    outside_secret_path = tmp_path / "outside.env"
    outside_secret_path.write_text("TOKEN=outside\n", encoding="utf-8")
    try:
        (repo_root_path / ".env").symlink_to(outside_secret_path)
    except OSError as symlink_error:
        pytest.skip(f"symlink creation is unavailable: {symlink_error}")

    policy_schema = build_default_project_worktree_resource_policy(repo_root_path)
    worktree_root_path = tmp_path / "worktree"
    worktree_root_path.mkdir()

    with pytest.raises(ValueError, match="escapes expected root"):
        materialize_project_worktree_resources(
            repo_root_path=repo_root_path,
            worktree_root_path=worktree_root_path,
            project_policy=policy_schema,
        )


def test_materialize_project_worktree_resources_fails_on_target_collision(
    tmp_path: Path,
) -> None:
    """Materialization should not overwrite existing worktree targets."""

    repo_root_path = _create_git_repo(tmp_path / "collision-repo")
    (repo_root_path / ".env").write_text("TOKEN=demo\n", encoding="utf-8")
    policy_schema = build_default_project_worktree_resource_policy(repo_root_path)
    worktree_root_path = tmp_path / "worktree"
    worktree_root_path.mkdir()
    (worktree_root_path / ".env").write_text("existing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="target already exists"):
        materialize_project_worktree_resources(
            repo_root_path=repo_root_path,
            worktree_root_path=worktree_root_path,
            project_policy=policy_schema,
        )
