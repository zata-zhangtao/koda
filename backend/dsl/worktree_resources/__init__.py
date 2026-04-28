"""Worktree local resource policy helpers.

This package owns policy schemas, repository scanning, and materialization
helpers for local runtime resources that should be copied or linked into task
worktrees.
"""

from backend.dsl.worktree_resources.schemas import (
    ProjectWorktreeResourcePolicySchema,
    ProjectWorktreeResourceRuleSchema,
    WorktreeResourceCandidateListSchema,
    WorktreeResourceCandidateSchema,
    WorktreeResourceGitState,
    WorktreeResourceMaterialization,
    WorktreeResourcePolicyConfirmation,
    WorktreeResourcePreviewRequestSchema,
)
from backend.dsl.worktree_resources.service import (
    build_default_project_worktree_resource_policy,
    build_project_worktree_resource_policy_note,
    materialize_project_worktree_resources,
    parse_project_worktree_resource_policy,
    preview_project_worktree_resource_candidates,
    resolve_project_worktree_resource_policy,
)

__all__ = [
    "ProjectWorktreeResourcePolicySchema",
    "ProjectWorktreeResourceRuleSchema",
    "WorktreeResourceCandidateListSchema",
    "WorktreeResourceCandidateSchema",
    "WorktreeResourceGitState",
    "WorktreeResourceMaterialization",
    "WorktreeResourcePolicyConfirmation",
    "WorktreeResourcePreviewRequestSchema",
    "build_default_project_worktree_resource_policy",
    "build_project_worktree_resource_policy_note",
    "materialize_project_worktree_resources",
    "parse_project_worktree_resource_policy",
    "preview_project_worktree_resource_candidates",
    "resolve_project_worktree_resource_policy",
]
