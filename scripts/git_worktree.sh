#!/usr/bin/env bash

# 将此函数放入 .zshrc 或 .bashrc
# 用法:
#   source ./scripts/git_worktree.sh && ai_worktree <新分支名> [--base <base_branch>] [--cmd [code_cmd]]
#   或直接执行:
#   ./scripts/git_worktree.sh <新分支名> [--base <base_branch>] [--cmd [code_cmd]]

ai_worktree_usage() {
    cat <<'EOF'
Usage:
  ai_worktree <new_branch_name> [--base <base_branch>] [--cmd [code_cmd]]

Options:
  --base <base_branch>
                    从指定本地分支创建 worktree。默认使用: main
  --cmd [code_cmd]  创建完成后自动执行: <code_cmd> --add <worktree_path>
                    不传 code_cmd 时默认使用: code
  -h, --help        显示帮助

Examples:
  ai_worktree feature-login
  ai_worktree feature-login --base develop
  ai_worktree feature-login --cmd
  ai_worktree feature-login --cmd code-insiders
  ./scripts/git_worktree.sh feature-login
  ./scripts/git_worktree.sh feature-login --base develop
  ./scripts/git_worktree.sh feature-login --cmd
  ./scripts/git_worktree.sh feature-login --cmd code-insiders
EOF
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

resolve_bootstrap_script_path() {
    local script_directory_path
    script_directory_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    printf '%s\n' "$script_directory_path/bootstrap_worktree_env.sh"
}

run_worktree_environment_bootstrap() {
    local source_root_path="$1"
    local target_root_path="$2"
    local bootstrap_script_path

    bootstrap_script_path="$(resolve_bootstrap_script_path)"
    if [ ! -f "$bootstrap_script_path" ]; then
        echo "❌ 未找到环境准备脚本: $bootstrap_script_path"
        return 1
    fi

    echo "📦 正在准备 worktree 环境 ..."
    if ! bash "$bootstrap_script_path" "$source_root_path" "$target_root_path"; then
        echo "❌ worktree 环境准备失败。"
        return 1
    fi

    return 0
}

function ai_worktree() {
    local branch_name=""
    local base_branch_name="${KODA_WORKTREE_BASE_BRANCH:-main}"
    local enable_vscode_add="false"
    local vscode_command_name="code"
    local repo_root_path=""
    local repo_parent_path=""
    local target_abs_path=""

    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h|--help)
                ai_worktree_usage
                return 0
                ;;
            --cmd)
                enable_vscode_add="true"
                if [ "$#" -gt 1 ] && [[ "$2" != -* ]]; then
                    vscode_command_name="$2"
                    shift
                fi
                ;;
            --cmd=*)
                enable_vscode_add="true"
                vscode_command_name="${1#--cmd=}"
                if [ -z "$vscode_command_name" ]; then
                    echo "❌ --cmd= 后需要提供命令名，例如: --cmd=code-insiders"
                    return 1
                fi
                ;;
            --base)
                if [ "$#" -le 1 ] || [[ "$2" == -* ]]; then
                    echo "❌ --base 后需要提供基底分支名，例如: --base develop"
                    return 1
                fi
                base_branch_name="$2"
                shift
                ;;
            --base=*)
                base_branch_name="${1#--base=}"
                if [ -z "$base_branch_name" ]; then
                    echo "❌ --base= 后需要提供基底分支名，例如: --base=develop"
                    return 1
                fi
                ;;
            -*)
                echo "❌ 未知参数: $1"
                ai_worktree_usage
                return 1
                ;;
            *)
                if [ -z "$branch_name" ]; then
                    branch_name="$1"
                else
                    echo "❌ 只允许一个分支名参数，收到多余参数: $1"
                    ai_worktree_usage
                    return 1
                fi
                ;;
        esac
        shift
    done

    if [ -z "$branch_name" ]; then
        echo "请提供分支名称！例如: ai_worktree feature-login"
        ai_worktree_usage
        return 1
    fi

    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "❌ 当前目录不是 Git 仓库，无法创建 worktree。"
        return 1
    fi

    repo_root_path="$(git rev-parse --show-toplevel)"
    repo_parent_path="$(dirname "$repo_root_path")"
    # 1. 约定 worktree 建立在仓库根目录上级的同名文件夹中
    target_abs_path="$repo_parent_path/$branch_name"
    if [ -e "$target_abs_path" ]; then
        echo "❌ 目标目录已存在: $target_abs_path"
        return 1
    fi

    if ! git -C "$repo_root_path" show-ref --verify --quiet "refs/heads/$base_branch_name"; then
        echo "❌ 基底分支不存在: $base_branch_name"
        return 1
    fi

    echo "🚀 正在创建 Git Worktree: $target_abs_path ..."
    if ! git -C "$repo_root_path" worktree add -b "$branch_name" "$target_abs_path" "$base_branch_name"; then
        echo "❌ Git worktree 创建失败。"
        return 1
    fi

    if ! run_worktree_environment_bootstrap "$repo_root_path" "$target_abs_path"; then
        return 1
    fi

    if [ "$enable_vscode_add" = "true" ]; then
        if ! command -v "$vscode_command_name" >/dev/null 2>&1; then
            echo "❌ 未找到命令: $vscode_command_name"
            echo "   请确认该 CLI 已安装并在 PATH 中。"
            return 1
        fi
        if ! "$vscode_command_name" --add "$target_abs_path"; then
            echo "❌ 执行失败: $vscode_command_name --add \"$target_abs_path\""
            return 1
        fi
        echo "🧩 已将目录加入工作区: $target_abs_path"
    fi

    echo "✅ 准备完毕！AI 可以开始在 $target_abs_path 愉快地写代码了。"
}

# If executed directly with bash, run ai_worktree with all CLI args.
# If sourced in shell profile, only function definitions are loaded.
if [ -n "${BASH_VERSION:-}" ] && [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    ai_worktree "$@"
fi
