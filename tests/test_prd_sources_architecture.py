"""Architecture boundary tests for the PRD source domain slice."""

from __future__ import annotations

import ast
from pathlib import Path


def test_prd_source_service_is_not_added_to_flat_services_directory() -> None:
    """PRD source implementation must not grow the legacy flat services directory."""
    assert not Path("backend/dsl/services/prd_source_service.py").exists()


def test_prd_source_routes_are_not_added_to_large_tasks_api_file() -> None:
    """PRD source routes should live in the prd_sources package."""
    tasks_api_text = Path("backend/dsl/api/tasks.py").read_text(encoding="utf-8")

    assert "prd-sources" not in tasks_api_text
    assert "select_pending_prd" not in tasks_api_text
    assert "import_prd" not in tasks_api_text


def test_prd_source_domain_has_no_framework_or_infrastructure_imports() -> None:
    """Domain layer should not depend on FastAPI, SQLAlchemy, ORM, or adapters."""
    forbidden_import_prefix_tuple = (
        "fastapi",
        "sqlalchemy",
        "backend.dsl.models",
        "backend.dsl.prd_sources.infrastructure",
        "frontend",
    )
    domain_file_path_list = sorted(Path("backend/dsl/prd_sources/domain").glob("*.py"))

    for domain_file_path in domain_file_path_list:
        parsed_module = ast.parse(domain_file_path.read_text(encoding="utf-8"))
        for ast_node in ast.walk(parsed_module):
            imported_module_name = _extract_imported_module_name(ast_node)
            if imported_module_name is None:
                continue
            assert not imported_module_name.startswith(forbidden_import_prefix_tuple), (
                f"{domain_file_path} imports forbidden dependency "
                f"{imported_module_name!r}"
            )


def _extract_imported_module_name(ast_node: ast.AST) -> str | None:
    """Extract the imported module name from an AST import node."""
    if isinstance(ast_node, ast.Import):
        return ast_node.names[0].name
    if isinstance(ast_node, ast.ImportFrom):
        return ast_node.module
    return None
