"""Remote requirement collaboration domain slice.

This package contains the manifest policy, Git remote infrastructure, GitHub PR
adapter, and application use cases for branch-backed requirement collaboration.
"""

from backend.dsl.remote_requirements.service import RemoteRequirementService

__all__ = ["RemoteRequirementService"]
