"""Tests for the DSL packaged public runtime mode."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import dsl.app as dsl_app_module


def test_packaged_runtime_serves_frontend_dist_and_spa_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`SERVE_FRONTEND_DIST=true` should serve built assets and SPA fallback."""
    frontend_dist_path = tmp_path / "frontend-dist"
    frontend_dist_path.mkdir(parents=True, exist_ok=True)
    (frontend_dist_path / "index.html").write_text(
        "<!doctype html><html><body>packaged-shell</body></html>",
        encoding="utf-8",
    )
    assets_directory_path = frontend_dist_path / "assets"
    assets_directory_path.mkdir(parents=True, exist_ok=True)
    (assets_directory_path / "app.js").write_text(
        "console.log('packaged');",
        encoding="utf-8",
    )

    media_storage_path = tmp_path / "media"
    monkeypatch.setattr(dsl_app_module, "ensure_database_schema_ready", lambda: None)
    monkeypatch.setattr(
        dsl_app_module,
        "_backfill_missing_project_repo_fingerprints",
        lambda: None,
    )
    monkeypatch.setattr(dsl_app_module.config, "SERVE_FRONTEND_DIST", True, raising=False)
    monkeypatch.setattr(
        dsl_app_module.config,
        "FRONTEND_DIST_PATH",
        frontend_dist_path,
        raising=False,
    )
    monkeypatch.setattr(
        dsl_app_module.config,
        "MEDIA_STORAGE_PATH",
        media_storage_path,
        raising=False,
    )

    application = dsl_app_module.create_application()
    test_client = TestClient(application)

    root_response = test_client.get("/")
    spa_response = test_client.get("/workspace/tasks/demo")
    asset_response = test_client.get("/assets/app.js")
    api_404_response = test_client.get("/api/not-found")
    health_response = test_client.get("/health")

    assert root_response.status_code == 200
    assert "packaged-shell" in root_response.text
    assert spa_response.status_code == 200
    assert "packaged-shell" in spa_response.text
    assert asset_response.status_code == 200
    assert asset_response.text == "console.log('packaged');"
    assert api_404_response.status_code == 404
    assert health_response.status_code == 200
    assert health_response.json()["service"] == "dsl"
