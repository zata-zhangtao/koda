#!/usr/bin/env bash

set -euo pipefail

worktree_bootstrap_usage() {
    cat <<'EOF'
Usage:
  ./scripts/bootstrap_worktree_env.sh <source_repo_path> <target_worktree_path>

Description:
  Copy .env files and prepare frontend / Python dependencies for a worktree.
EOF
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

discover_frontend_project_directories() {
    local search_root_path="$1"

    if [ -z "$search_root_path" ] || [ ! -d "$search_root_path" ]; then
        return 0
    fi

    if [ -f "$search_root_path/package.json" ]; then
        printf '%s\n' "$search_root_path"
    fi

    while IFS= read -r nested_package_json_path; do
        dirname "$nested_package_json_path"
    done < <(
        find "$search_root_path" \
            \( -type d \( -name ".git" -o -name ".venv" -o -name "node_modules" -o -name "site" \) -prune \) -o \
            -mindepth 2 -type f -name "package.json" -print
    )
}

resolve_frontend_dependency_strategy() {
    local configured_strategy="${WORKTREE_FRONTEND_STRATEGY:-}"

    if [ -z "$configured_strategy" ]; then
        echo "install-per-worktree"
        return 0
    fi

    case "$configured_strategy" in
        install-per-worktree|symlink-from-main)
            echo "$configured_strategy"
            ;;
        *)
            echo "WARN: unknown WORKTREE_FRONTEND_STRATEGY=$configured_strategy; fallback to install-per-worktree." >&2
            echo "install-per-worktree"
            ;;
    esac
}

setup_frontend_node_modules_symlinks() {
    local source_root_path="$1"
    local target_root_path="$2"

    if [ -z "$source_root_path" ] || [ -z "$target_root_path" ]; then
        return 0
    fi

    if [ ! -d "$source_root_path" ] || [ ! -d "$target_root_path" ]; then
        return 0
    fi

    local linked_project_count=0

    while IFS= read -r source_frontend_dir; do
        local relative_frontend_path="${source_frontend_dir#"$source_root_path"/}"
        local target_frontend_dir="$target_root_path"
        local frontend_display_path="."

        if [ "$source_frontend_dir" != "$source_root_path" ]; then
            target_frontend_dir="$target_root_path/$relative_frontend_path"
            frontend_display_path="$relative_frontend_path"
        fi

        local source_node_modules_path="$source_frontend_dir/node_modules"
        local target_node_modules_path="$target_frontend_dir/node_modules"

        if [ ! -d "$source_node_modules_path" ]; then
            echo "INFO: source frontend directory has no node_modules; skip symlink: $frontend_display_path"
            continue
        fi

        if [ -e "$target_node_modules_path" ]; then
            continue
        fi

        if [ ! -d "$target_frontend_dir" ]; then
            mkdir -p "$target_frontend_dir"
        fi

        if ln -s "$source_node_modules_path" "$target_node_modules_path"; then
            echo "INFO: linked node_modules for $frontend_display_path"
            linked_project_count=$((linked_project_count + 1))
        else
            echo "ERROR: failed to create node_modules symlink: $target_node_modules_path" >&2
        fi
    done < <(discover_frontend_project_directories "$source_root_path")

    if [ "$linked_project_count" -eq 0 ]; then
        echo "INFO: no frontend node_modules symlinks were created."
    fi
}

install_frontend_dependencies_in_current_directory() {
    if [ -f pnpm-lock.yaml ]; then
        if ! command_exists pnpm; then
            echo "WARN: found pnpm-lock.yaml but pnpm is unavailable; skip frontend install."
            return 0
        fi
        echo "INFO: running pnpm install --ignore-scripts"
        pnpm install --ignore-scripts
        return 0
    fi

    if [ -f package-lock.json ]; then
        if ! command_exists npm; then
            echo "WARN: found package-lock.json but npm is unavailable; skip frontend install."
            return 0
        fi
        echo "INFO: running npm ci --ignore-scripts"
        npm ci --ignore-scripts
        return 0
    fi

    if [ -f yarn.lock ]; then
        if ! command_exists yarn; then
            echo "WARN: found yarn.lock but yarn is unavailable; skip frontend install."
            return 0
        fi
        echo "INFO: running yarn install --ignore-scripts"
        yarn install --ignore-scripts
        return 0
    fi

    if [ -f bun.lock ] || [ -f bun.lockb ]; then
        if ! command_exists bun; then
            echo "WARN: found Bun lockfile but bun is unavailable; skip frontend install."
            return 0
        fi
        echo "INFO: running bun install --ignore-scripts"
        bun install --ignore-scripts
        return 0
    fi

    if [ -f package.json ]; then
        if ! command_exists npm; then
            echo "WARN: found package.json but npm is unavailable; skip frontend install."
            return 0
        fi
        echo "INFO: running npm install --ignore-scripts"
        npm install --ignore-scripts
    fi
}

install_frontend_dependencies_in_directory() {
    local frontend_project_path="$1"
    local frontend_display_path="$2"

    if [ -z "$frontend_project_path" ] || [ ! -d "$frontend_project_path" ]; then
        return 0
    fi

    if [ ! -f "$frontend_project_path/package.json" ]; then
        return 0
    fi

    echo "INFO: preparing frontend directory: $frontend_display_path"
    (
        cd "$frontend_project_path"
        install_frontend_dependencies_in_current_directory
    )
}

install_frontend_dependencies_for_worktree() {
    local worktree_root_path="$1"
    local discovered_project_count=0
    local frontend_project_path=""
    local relative_frontend_path=""
    local frontend_display_path=""

    while IFS= read -r frontend_project_path; do
        if [ -z "$frontend_project_path" ]; then
            continue
        fi

        discovered_project_count=$((discovered_project_count + 1))
        relative_frontend_path="${frontend_project_path#"$worktree_root_path"/}"
        frontend_display_path="."
        if [ "$frontend_project_path" != "$worktree_root_path" ]; then
            frontend_display_path="$relative_frontend_path"
        fi

        install_frontend_dependencies_in_directory \
            "$frontend_project_path" \
            "$frontend_display_path"
    done < <(discover_frontend_project_directories "$worktree_root_path")

    if [ "$discovered_project_count" -eq 0 ]; then
        echo "INFO: no package.json files found; skip frontend install."
    fi
}

install_python_dependencies() {
    local worktree_root_path="$1"

    if [ ! -f "$worktree_root_path/pyproject.toml" ]; then
        return 0
    fi

    if ! command_exists uv; then
        echo "WARN: found pyproject.toml but uv is unavailable; skip Python dependency install."
        return 0
    fi

    echo "INFO: running uv sync --all-extras"
    (
        cd "$worktree_root_path"
        uv sync --all-extras
    )
}

copy_env_files_to_worktree() {
    local source_root_path="$1"
    local target_root_path="$2"
    local copied_env_file_count=0
    local source_env_example_path="$source_root_path/.env.example"
    local source_env_file_path=""
    local relative_env_file_path=""
    local target_env_file_path=""

    while IFS= read -r source_env_file_path; do
        relative_env_file_path="${source_env_file_path#"$source_root_path"/}"
        target_env_file_path="$target_root_path/$relative_env_file_path"
        mkdir -p "$(dirname "$target_env_file_path")"
        cp "$source_env_file_path" "$target_env_file_path"
        copied_env_file_count=$((copied_env_file_count + 1))
    done < <(
        find "$source_root_path" -type f -name ".env*" \
            -not -path "$source_root_path/.git/*" \
            -not -path "$source_root_path/.venv/*" \
            -not -path "$source_root_path/.uv-cache/*" \
            -not -path "$source_root_path/site/*"
    )

    if [ "$copied_env_file_count" -gt 0 ]; then
        echo "INFO: copied $copied_env_file_count .env files into the worktree."
        return 0
    fi

    if [ -f "$source_env_example_path" ] && [ ! -f "$target_root_path/.env" ]; then
        cp "$source_env_example_path" "$target_root_path/.env"
        echo "INFO: no .env files found; created .env from .env.example."
        return 0
    fi

    echo "INFO: no .env files found; nothing copied."
}

bootstrap_worktree_environment() {
    local source_root_path="$1"
    local target_root_path="$2"

    if [ -z "$source_root_path" ] || [ -z "$target_root_path" ]; then
        echo "ERROR: source and target paths are required." >&2
        return 1
    fi

    if [ ! -d "$source_root_path" ]; then
        echo "ERROR: source repository path does not exist: $source_root_path" >&2
        return 1
    fi

    if [ ! -d "$target_root_path" ]; then
        echo "ERROR: target worktree path does not exist: $target_root_path" >&2
        return 1
    fi

    copy_env_files_to_worktree "$source_root_path" "$target_root_path"

    local frontend_dependency_strategy
    frontend_dependency_strategy="$(resolve_frontend_dependency_strategy)"
    echo "INFO: frontend dependency strategy: $frontend_dependency_strategy"

    if [ "$frontend_dependency_strategy" = "symlink-from-main" ]; then
        setup_frontend_node_modules_symlinks "$source_root_path" "$target_root_path"
    else
        if [ "${WORKTREE_SKIP_FRONTEND_INSTALL:-false}" = "true" ]; then
            echo "WARN: WORKTREE_SKIP_FRONTEND_INSTALL=true; skip frontend dependency install."
        else
            install_frontend_dependencies_for_worktree "$target_root_path"
        fi
    fi

    install_python_dependencies "$target_root_path"
}

if [ -n "${BASH_VERSION:-}" ] && [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    if [ "$#" -ne 2 ]; then
        worktree_bootstrap_usage
        exit 1
    fi
    bootstrap_worktree_environment "$1" "$2"
fi
