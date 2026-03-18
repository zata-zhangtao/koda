# Default recipe (runs when you type 'just')
default:
    @just --list

# Install all dependencies excluding dev
prod-sync:
    uv sync --no-dev

# 安装全部（主依赖 + dev + 所有 extras）
full-sync:
    uv sync --all-extras

# Sync dependencies from lock file (including dev)
sync:
    uv sync

# Start dev environment (full sync + pre-commit hooks)
dev:
    uv sync --all-extras
    uv run pre-commit install

# Preview MkDocs locally
docs-serve:
    uv run mkdocs serve

# Build MkDocs site in strict mode
docs-build:
    uv run mkdocs build --strict

# Run the main application
run:
    uv run python main.py

# Remove cache files and build artifacts
clean:
    @echo "Cleaning cache files..."
    @rm -rf .ruff_cache
    @rm -rf __pycache__
    @find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    @find . -type f -name "*.pyc" -delete 2>/dev/null || true
    @find . -type f -name "*.pyo" -delete 2>/dev/null || true
    @find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
    @echo "Clean complete!"

staged_changes:
    git diff --cached > staged_changes.diff

# ============================
# DevStream Log (DSL) Commands
# ============================

# 安装前端依赖
install-frontend:
    cd frontend && npm install

# 启动前端开发服务器
dev-frontend:
    cd frontend && npm run dev

# 构建前端
build-frontend:
    cd frontend && npm run build

# 创建数据目录
setup-data:
    mkdir -p data/media/original
    mkdir -p data/media/thumbnail

# 启动 DSL 完整开发环境 (后端 + 前端)
dsl-dev:
    #!/usr/bin/env bash
    set -euo pipefail

    ensure_port_available() {
        local port="$1"
        local service_name="$2"

        if lsof -tiTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
            echo "Port ${port} is already in use, so ${service_name} cannot start."
            echo "Current listener:"
            lsof -nP -iTCP:"${port}" -sTCP:LISTEN || true
            echo "Stop the existing process and rerun 'just dsl-dev'."
            return 1
        fi
    }

    terminate_process_tree() {
        local pid="$1"

        if [[ -z "${pid}" ]]; then
            return 0
        fi

        pkill -TERM -P "${pid}" 2>/dev/null || true
        kill "${pid}" 2>/dev/null || true
    }

    cleanup() {
        local exit_code=$?
        trap - EXIT INT TERM

        terminate_process_tree "${FRONTEND_PID:-}"
        terminate_process_tree "${BACKEND_PID:-}"

        wait "${FRONTEND_PID:-}" 2>/dev/null || true
        wait "${BACKEND_PID:-}" 2>/dev/null || true

        exit "${exit_code}"
    }

    echo "Starting DSL development environment..."
    just setup-data
    ensure_port_available 8000 "the backend"
    ensure_port_available 5173 "the frontend"

    trap cleanup EXIT INT TERM

    uv run python main.py &
    BACKEND_PID=$!

    (
        cd frontend
        npm run dev
    ) &
    FRONTEND_PID=$!

    echo "Backend PID: $BACKEND_PID"
    echo "Frontend PID: $FRONTEND_PID"

    while true; do
        if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
            backend_exit_code=0
            wait "${BACKEND_PID}" || backend_exit_code=$?
            echo "Backend exited. Shutting down DSL development environment."
            exit "${backend_exit_code}"
        fi

        if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
            frontend_exit_code=0
            wait "${FRONTEND_PID}" || frontend_exit_code=$?
            echo "Frontend exited. Shutting down DSL development environment."
            exit "${frontend_exit_code}"
        fi

        sleep 1
    done
