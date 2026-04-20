# Default recipe (runs when you type 'just')
default:
    @just --list

# Install all dependencies excluding dev
prod-sync:
    uv sync --no-dev

# 安装全部（主依赖 + dev + 所有 extras）
# Usage:
#   just full-sync
#   just full-sync install_completion=true
# Install all dependencies including dev/extras; pass `true` to also install bash completion.
full-sync install_completion="false":
    #!/usr/bin/env bash
    set -euo pipefail
    uv sync --all-extras
    if [ "{{install_completion}}" = "true" ] && [ -z "${CI:-}" ]; then
        just install-worktree-completion
    fi

# Sync dependencies from lock file (including dev)
sync:
    uv sync

# Start dev environment (full sync + pre-commit hooks)
dev:
    uv sync --all-extras
    uv run pre-commit install

# Preview MkDocs locally
docs-serve port="8000":
    WATCHDOG_USE_POLLING=1 uv run mkdocs serve -a 127.0.0.1:{{port}}

# Build MkDocs site in strict mode
docs-build:
    uv run mkdocs build --strict

# Run the main application; pass `all` to start the full DSL dev environment.
run mode="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{mode}}" = "all" ]; then
        exec just dsl-dev
    fi
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

# Build a release zip (does NOT modify local workspace)
release:
    uv run python scripts/release.py

staged_changes:
    git diff --cached > staged_changes.diff

# Git worktree helper (wrapper for scripts/git_worktree.sh)
# Usage:
#   just worktree <branch_name>
#   just worktree <branch_name> --cmd
#   just worktree <branch_name> --cmd code-insiders
#   just worktree <branch_name> --cmd trae
#   just worktree <branch_name> enter_shell=false
#   just worktree <branch_name> --cmd trae enter_shell=false
# Create a Git worktree and optionally enter its shell.
worktree branch_name arg2="" arg3="" arg4="":
    #!/usr/bin/env bash
    set -euo pipefail

    worktree_command=(./scripts/git_worktree.sh "{{branch_name}}")
    enter_shell_value="true"
    expect_code_command="false"

    for raw_arg in "{{arg2}}" "{{arg3}}" "{{arg4}}"; do
        if [ -z "$raw_arg" ]; then
            continue
        fi

        if [ "$expect_code_command" = "true" ]; then
            case "$raw_arg" in
                --cmd|--cmd=*|enter_shell=true|enter_shell=false)
                    expect_code_command="false"
                    ;;
                *)
                    worktree_command+=("$raw_arg")
                    expect_code_command="false"
                    continue
                    ;;
            esac
        fi

        case "$raw_arg" in
            --cmd)
                worktree_command+=(--cmd)
                expect_code_command="true"
                ;;
            --cmd=*)
                worktree_command+=("$raw_arg")
                ;;
            enter_shell=true)
                enter_shell_value="true"
                ;;
            enter_shell=false)
                enter_shell_value="false"
                ;;
            *)
                echo "Invalid argument: $raw_arg"
                echo "Usage: just worktree <branch_name> [--cmd [code_cmd]] [enter_shell=false]"
                exit 1
                ;;
        esac
    done

    "${worktree_command[@]}"

    if [ "$enter_shell_value" = "true" ]; then
        target_worktree_path="$(dirname "$(git rev-parse --show-toplevel)")/{{branch_name}}"
        echo "Entering worktree shell: $target_worktree_path"
        echo "Run 'exit' to return to previous shell."
        cd "$target_worktree_path"
        if [ -n "${TERM:-}" ] && [ "${TERM}" != "dumb" ]; then
            printf '\033]0;%s\007' "wt:{{branch_name}}"
        fi
        worktree_shell_rcfile="$(mktemp)"
        printf '%s\n' \
            'if [ -f "$HOME/.bashrc" ]; then' \
            '    source "$HOME/.bashrc"' \
            'fi' \
            'if [ -n "${WORKTREE_BRANCH_NAME:-}" ]; then' \
            '    PS1="(wt:${WORKTREE_BRANCH_NAME}) ${PS1:-\u@\h:\w\$ }"' \
            'fi' \
            'if [ -n "${WORKTREE_SHELL_RCFILE:-}" ] && [ -f "${WORKTREE_SHELL_RCFILE}" ]; then' \
            '    rm -f "${WORKTREE_SHELL_RCFILE}" 2>/dev/null || true' \
            '    unset WORKTREE_SHELL_RCFILE' \
            'fi' \
            > "$worktree_shell_rcfile"
        exec env WORKTREE_BRANCH_NAME="{{branch_name}}" WORKTREE_SHELL_RCFILE="$worktree_shell_rcfile" bash --rcfile "$worktree_shell_rcfile" -i
    fi

# Git worktree merge helper (wrapper for scripts/git_worktree_merge.sh)
# Usage:
#   just worktree-merge <feature_branch>
#   just worktree-merge <feature_branch> <base_branch>
#   just worktree-merge <feature_branch> <base_branch> flags="--cleanup --delete-remote"
#   just worktree-merge <feature_branch> flags="-d"
# Merge or clean up a feature worktree branch via the helper script.
worktree-merge feature_branch base_branch="main" flags="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "{{flags}}" ]; then
        ./scripts/git_worktree_merge.sh "{{feature_branch}}" "{{base_branch}}" {{flags}}
    else
        ./scripts/git_worktree_merge.sh "{{feature_branch}}" "{{base_branch}}"
    fi

# Delete-only cleanup for a feature worktree/branch
# Usage:
#   just worktree-delete <feature_branch>
# Delete a feature worktree/branch without merging.
worktree-delete feature_branch:
    ./scripts/git_worktree_merge.sh "{{feature_branch}}" -d

# Doctor / cleanup-check for worktrees
# Usage:
#   just worktree-doctor
#   just worktree-doctor <feature_branch>
# Inspect worktree cleanup state globally or for one branch.
worktree-doctor feature_branch="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "{{feature_branch}}" ]; then
        ./scripts/git_worktree_merge.sh --doctor "{{feature_branch}}"
    else
        ./scripts/git_worktree_merge.sh --doctor
    fi

# Install global bash completion for just worktree recipes (one-time setup)
# Usage:
#   just install-worktree-completion
# Install bash completion for the just worktree helper recipes.
install-worktree-completion:
    #!/usr/bin/env bash
    set -euo pipefail
    completion_script_source_path="{{justfile_directory()}}/scripts/just_worktree_completion.bash"
    completion_directory_path="$HOME/.config/just"
    completion_script_path="$completion_directory_path/worktree_completion.bash"
    shell_rc_path="$HOME/.bashrc"
    source_line="[ -f \"$completion_script_path\" ] && source \"$completion_script_path\""
    mkdir -p "$completion_directory_path"
    cp "$completion_script_source_path" "$completion_script_path"
    if [ ! -f "$shell_rc_path" ]; then
        touch "$shell_rc_path"
    fi
    if ! grep -Fqx "$source_line" "$shell_rc_path"; then
        printf '\n%s\n' "$source_line" >> "$shell_rc_path"
        echo "Added completion source line to $shell_rc_path"
    else
        echo "Completion source line already exists in $shell_rc_path"
    fi
    echo "Installed completion script at $completion_script_path"
    echo "Run: source \"$shell_rc_path\""

# Lint and format check (ruff)
lint:
    uv run pre-commit run --all-files

# Run tests (usage: just test [all|local|real])
#   just test        - Run local tests (no API keys needed)
#   just test all    - Run all tests
#   just test real   - Run tests requiring API keys
# Run pytest in local/all/real modes.
test type="local":
    #!/usr/bin/env bash
    set -e
    if [ "{{type}}" = "all" ]; then
        uv run pytest tests/ -v
    elif [ "{{type}}" = "real" ]; then
        uv run pytest tests/ -v -k "expensive or not expensive"
    else
        uv run pytest tests/ -v --ignore=tests/test_model_loader_real.py -m "not expensive"
    fi

# Export all .env* files recursively into a zip archive
export-env-zip output="":
    #!/usr/bin/env bash
    uv run python - <<'PY'
    from pathlib import Path
    import sys
    import zipfile

    project_root_path = Path(r"{{justfile_directory()}}")
    configured_output_name = r"{{output}}".strip()
    default_output_directory_path = project_root_path.parent / "mysecrets"
    default_output_zip_path = default_output_directory_path / f"{project_root_path.name}.zip"
    if configured_output_name:
        configured_output_path = Path(configured_output_name)
        output_zip_path = (
            configured_output_path
            if configured_output_path.is_absolute()
            else project_root_path / configured_output_path
        )
    else:
        output_zip_path = default_output_zip_path
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    env_file_paths = sorted(
        path
        for path in project_root_path.rglob("*")
        if path.is_file() and path.name.startswith(".env")
    )
    env_file_paths = [path for path in env_file_paths if path != output_zip_path]

    if not env_file_paths:
        sys.exit("No files starting with .env were found in this project.")

    if output_zip_path.exists():
        output_zip_path.unlink()

    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_archive_file:
        for env_file_path in env_file_paths:
            archived_relative_path = env_file_path.relative_to(project_root_path)
            zip_archive_file.write(env_file_path, arcname=str(archived_relative_path))

    print(f"Created {output_zip_path} with {len(env_file_paths)} files:")
    for env_file_path in env_file_paths:
        archived_relative_path = env_file_path.relative_to(project_root_path)
        print(f" - {archived_relative_path}")
    PY

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

# 构建公网打包前端
public-build:
    cd frontend && npm run build

# 启动 DSL 公网打包模式（同源托管 frontend/dist）
public-run:
    SERVE_FRONTEND_DIST=true uv run python main.py

# 启动本机隧道 agent
public-agent:
    #!/usr/bin/env bash
    set -euo pipefail

    if [[ ! -f .env ]]; then
        echo "Missing .env. Copy deploy/public-forward/agent.env.example to .env first."
        exit 1
    fi

    set -a
    source ./.env
    set +a

    uv run python -m forwarding_service.agent.main

# 公网模式：同时启动 DSL 应用 + 隧道 agent（两个进程，任一退出则全部终止）
public-serve:
    #!/usr/bin/env bash
    set -euo pipefail

    if [[ ! -f .env ]]; then
        echo "Missing .env. Copy deploy/public-forward/agent.env.example to .env first."
        exit 1
    fi

    terminate_process_tree() {
        local pid="$1"
        if [[ -z "${pid}" ]]; then return 0; fi
        pkill -TERM -P "${pid}" 2>/dev/null || true
        kill "${pid}" 2>/dev/null || true
    }

    cleanup() {
        trap - EXIT INT TERM
        terminate_process_tree "${APP_PID:-}"
        terminate_process_tree "${AGENT_PID:-}"
        wait "${APP_PID:-}" 2>/dev/null || true
        wait "${AGENT_PID:-}" 2>/dev/null || true
    }

    trap cleanup EXIT INT TERM

    SERVE_FRONTEND_DIST=true uv run python main.py &
    APP_PID=$!

    set -a
    source ./.env
    set +a

    uv run python -m forwarding_service.agent.main &
    AGENT_PID=$!

    echo "DSL app PID: ${APP_PID}  |  Agent PID: ${AGENT_PID}"

    while true; do
        if ! kill -0 "${APP_PID}" 2>/dev/null; then
            echo "DSL app exited. Shutting down."
            exit 1
        fi
        if ! kill -0 "${AGENT_PID}" 2>/dev/null; then
            echo "Agent exited. Shutting down."
            exit 1
        fi
        sleep 1
    done

# 创建数据目录
setup-data:
    mkdir -p data/media/original
    mkdir -p data/media/thumbnail

# 启动 DSL 完整开发环境 (后端 + 前端)
# Usage:
#   just dsl-dev
#   just dsl-dev backend_port=8100 frontend_port=5174
#   just dsl-dev 8100 5174
dsl-dev arg1="" arg2="":
    #!/usr/bin/env bash
    set -euo pipefail

    validate_port_number() {
        local port="$1"
        local service_name="$2"

        if ! [[ "${port}" =~ ^[0-9]+$ ]] || ((10#${port} < 1 || 10#${port} > 65535)); then
            echo "Invalid ${service_name} port: ${port}. Expected an integer between 1 and 65535."
            return 1
        fi
    }

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

    find_free_port() {
        local port="$1"
        while lsof -tiTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; do
            port=$((port + 1))
        done
        echo "${port}"
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
    REQUESTED_BACKEND_PORT=""
    REQUESTED_FRONTEND_PORT=""
    POSITIONAL_PORTS=()

    for raw_arg in "{{arg1}}" "{{arg2}}"; do
        if [[ -z "${raw_arg}" ]]; then
            continue
        fi

        case "${raw_arg}" in
            backend_port=*)
                REQUESTED_BACKEND_PORT="${raw_arg#backend_port=}"
                ;;
            frontend_port=*)
                REQUESTED_FRONTEND_PORT="${raw_arg#frontend_port=}"
                ;;
            *)
                POSITIONAL_PORTS+=("${raw_arg}")
                ;;
        esac
    done

    if [[ -z "${REQUESTED_BACKEND_PORT}" ]] && (( ${#POSITIONAL_PORTS[@]} >= 1 )); then
        REQUESTED_BACKEND_PORT="${POSITIONAL_PORTS[0]}"
    fi

    if [[ -z "${REQUESTED_FRONTEND_PORT}" ]] && (( ${#POSITIONAL_PORTS[@]} >= 2 )); then
        REQUESTED_FRONTEND_PORT="${POSITIONAL_PORTS[1]}"
    fi

    FRONTEND_PORT="${REQUESTED_FRONTEND_PORT:-5173}"

    validate_port_number "${FRONTEND_PORT}" "frontend"

    if [[ -n "${REQUESTED_BACKEND_PORT}" ]]; then
        validate_port_number "${REQUESTED_BACKEND_PORT}" "backend"
        BACKEND_PORT="${REQUESTED_BACKEND_PORT}"
        ensure_port_available "${BACKEND_PORT}" "the backend"
    else
        BACKEND_PORT=$(find_free_port 8000)
        if [[ "${BACKEND_PORT}" != "8000" ]]; then
            echo "Port 8000 is in use, using port ${BACKEND_PORT} for the backend instead."
        fi
    fi

    ensure_port_available "${FRONTEND_PORT}" "the frontend"

    trap cleanup EXIT INT TERM

    KODA_SERVER_PORT="${BACKEND_PORT}" KODA_DEV_FRONTEND_PORT="${FRONTEND_PORT}" KODA_TUNNEL_UPSTREAM_URL="http://127.0.0.1:${BACKEND_PORT}" uv run python main.py &
    BACKEND_PID=$!

    (
        cd frontend
        npm install
        KODA_VITE_PORT="${FRONTEND_PORT}" KODA_VITE_BACKEND_TARGET="http://127.0.0.1:${BACKEND_PORT}" npm run dev
    ) &
    FRONTEND_PID=$!

    echo "Backend PID: $BACKEND_PID"
    echo "Frontend PID: $FRONTEND_PID"
    echo "Backend URL: http://127.0.0.1:${BACKEND_PORT}"
    echo "Frontend URL: http://127.0.0.1:${FRONTEND_PORT}"

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
