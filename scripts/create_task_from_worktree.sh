#!/usr/bin/env bash
# 基于当前 git worktree 创建 Koda 需求卡片（Task）
#
# 用法:
#   source ./scripts/create_task_from_worktree.sh
#   或在 .zshrc/.bashrc 中 source 后直接调用:
#   create_koda_task "需求标题" [--port 8000] [--project <project_id>]
#
# 该脚本会检测当前目录是否在 git worktree 中，自动获取分支名和路径，
# 然后调用 Koda API 创建 task，将当前 worktree 直接关联到新 task。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KODA_DEFAULT_PORT=8000

create_koda_task_usage() {
    cat <<'EOF'
用法:
  create_koda_task "需求标题" [选项]

选项:
  --port <port>        Koda 后端端口（默认: 8000）
  --project <id>       关联的 Project ID（可选）
  --base <branch>      Worktree 基底分支名（默认: main）
  --brief <text>       需求描述文本（可选）
  --auto-execute       PRD 就绪后自动执行（可选）
  -h, --help           显示帮助

示例:
  create_koda_task "实现用户登录功能"
  create_koda_task "优化数据库查询" --port 8100
  create_koda_task "重构 API 路由" --project "abc-123" --brief "将现有路由迁移到新的路径结构"
EOF
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

detect_git_worktree_context() {
    local worktree_path_str branch_name_str repo_root_str

    # 检测是否在 git 仓库中
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "❌ 当前目录不是 Git 仓库，无法创建 task。"
        return 1
    fi

    # 获取 worktree 顶层路径
    worktree_path_str="$(git rev-parse --show-toplevel 2>/dev/null)" || {
        echo "❌ 无法获取 Git worktree 顶层路径。"
        return 1
    }

    # 获取当前分支名
    branch_name_str="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || branch_name_str=""

    if [ -z "$branch_name_str" ] || [ "$branch_name_str" = "HEAD" ]; then
        echo "⚠️  当前处于 detached HEAD 状态，将使用目录名作为分支名。"
        branch_name_str="$(basename "$worktree_path_str")"
    fi

    # 获取主仓库根目录（用于关联 Project 时验证）
    repo_root_str="$(git rev-parse --show-superproject-working-tree 2>/dev/null)" || repo_root_str=""
    if [ -z "$repo_root_str" ]; then
        # worktree 的主仓库：对于 git worktree，主仓库的 .git 是一个文件
        local git_dir
        git_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || git_dir=""
        if [ -n "$git_dir" ] && [ -d "$git_dir" ]; then
            repo_root_str="$(cd "$git_dir/.." && pwd 2>/dev/null)" || repo_root_str=""
        fi
    fi

    echo "worktree_path=${worktree_path_str}"
    echo "branch_name=${branch_name_str}"
    echo "repo_root=${repo_root_str}"
}

validate_worktree_context() {
    local worktree_path_str="$1"

    # 检查 worktree 是否为 git worktree（通过 .git 文件判断）
    if [ -f "$worktree_path_str/.git" ]; then
        return 0
    fi

    # 也可能是主仓库的根目录
    if [ -d "$worktree_path_str/.git" ]; then
        echo "⚠️  当前目录是主仓库而不是 worktree。继续执行..."
        return 0
    fi

    echo "⚠️  无法确认 '$worktree_path_str' 是 git worktree。继续执行..."
    return 0
}

function create_koda_task() {
    local task_title_str=""
    local backend_port_num="$KODA_DEFAULT_PORT"
    local project_id_str=""
    local base_branch_name_str="main"
    local requirement_brief_str=""
    local auto_execute_flag=false

    # 解析参数
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -h|--help)
                create_koda_task_usage
                return 0
                ;;
            --port)
                if [ "$#" -le 1 ] || [[ "$2" == -* ]]; then
                    echo "❌ --port 后需要提供端口号。"
                    return 1
                fi
                backend_port_num="$2"
                shift
                ;;
            --port=*)
                backend_port_num="${1#--port=}"
                ;;
            --project)
                if [ "$#" -le 1 ] || [[ "$2" == -* ]]; then
                    echo "❌ --project 后需要提供 Project ID。"
                    return 1
                fi
                project_id_str="$2"
                shift
                ;;
            --project=*)
                project_id_str="${1#--project=}"
                ;;
            --base)
                if [ "$#" -le 1 ] || [[ "$2" == -* ]]; then
                    echo "❌ --base 后需要提供分支名。"
                    return 1
                fi
                base_branch_name_str="$2"
                shift
                ;;
            --base=*)
                base_branch_name_str="${1#--base=}"
                ;;
            --brief)
                if [ "$#" -le 1 ]; then
                    echo "❌ --brief 后需要提供描述文本。"
                    return 1
                fi
                requirement_brief_str="$2"
                shift
                ;;
            --brief=*)
                requirement_brief_str="${1#--brief=}"
                ;;
            --auto-execute)
                auto_execute_flag=true
                ;;
            -*)
                echo "❌ 未知参数: $1"
                create_koda_task_usage
                return 1
                ;;
            *)
                if [ -z "$task_title_str" ]; then
                    task_title_str="$1"
                else
                    echo "❌ 只允许一个标题参数，收到多余参数: $1"
                    create_koda_task_usage
                    return 1
                fi
                ;;
        esac
        shift
    done

    if [ -z "$task_title_str" ]; then
        echo "请提供需求标题！例如: create_koda_task \"实现登录功能\""
        create_koda_task_usage
        return 1
    fi

    # 检测当前 worktree 上下文
    echo "🔍 正在检测当前 Git worktree 上下文..."
    local context_output context_worktree context_branch context_repo
    context_output="$(detect_git_worktree_context)" || return 1

    context_worktree="$(echo "$context_output" | grep "^worktree_path=" | cut -d= -f2-)"
    context_branch="$(echo "$context_output" | grep "^branch_name=" | cut -d= -f2-)"
    context_repo="$(echo "$context_output" | grep "^repo_root=" | cut -d= -f2-)"

    if [ -z "$context_worktree" ]; then
        echo "❌ 无法获取 worktree 路径。"
        return 1
    fi

    echo "📂 Worktree 路径: $context_worktree"
    echo "🌿 当前分支: $context_branch"
    echo "📦 仓库根目录: $context_repo"
    echo ""

    # 验证 worktree
    validate_worktree_context "$context_worktree"

    # 检查 Koda 后端是否可访问
    local koda_api_base="http://127.0.0.1:${backend_port_num}/api"
    echo "🔌 正在检查 Koda 后端 ($koda_api_base)..."

    if command_exists curl; then
        if ! curl -sf "$koda_api_base/run-accounts" >/dev/null 2>&1; then
            echo "❌ 无法连接到 Koda 后端（端口 $backend_port_num）。请确认 Koda 正在运行。"
            echo "   提示：可以通过 --port 参数指定其他端口。"
            return 1
        fi
    else
        echo "⚠️  未找到 curl，跳过后端连通性检查。"
    fi

    echo "✅ Koda 后端已连接。"
    echo ""

    # 构建 JSON 请求体
    local json_payload
    json_payload="$(
        cat <<JSONEOF
{
  "task_title": $(echo "$task_title_str" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'),
  "worktree_base_branch_name": "$base_branch_name_str",
  "worktree_path": "$context_worktree",
  "task_branch_name": "$context_branch"$(if [ -n "$project_id_str" ]; then echo ","; echo "  \"project_id\": \"$project_id_str\""; fi)$(if [ -n "$requirement_brief_str" ]; then echo ","; echo "  \"requirement_brief\": $(echo "$requirement_brief_str" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')"; fi)$(if [ "$auto_execute_flag" = true ]; then echo ","; echo "  \"auto_confirm_prd_and_execute\": true"; fi)
}
JSONEOF
    )"

    echo "📝 正在创建 Task: $task_title_str"
    echo ""

    # 调用 Koda API 创建 task
    if command_exists curl; then
        local http_status_code api_response
        api_response="$(mktemp)"
        http_status_code="$(curl -s -o "$api_response" -w "%{http_code}" \
            -X POST "$koda_api_base/tasks" \
            -H "Content-Type: application/json" \
            -d "$json_payload")" || {
            rm -f "$api_response"
            echo "❌ API 请求失败。"
            return 1
        }

        if [ "$http_status_code" = "201" ]; then
            local task_id task_title
            task_id="$(python3 -c "import json; data=json.load(open('$api_response')); print(data.get('id',''))")"
            task_title="$(python3 -c "import json; data=json.load(open('$api_response')); print(data.get('task_title',''))")"
            echo "✅ Task 创建成功！"
            echo "   ID: $task_id"
            echo "   标题: $task_title"
            echo "   Worktree: $context_worktree"
            echo "   分支: $context_branch"
            echo ""
            echo "💡 下一步：在 Koda Dashboard 中打开该任务，点击「开始任务」即可进入工作流。"
            echo "   由于已关联现有 worktree，系统不会创建新的 worktree。"
            rm -f "$api_response"
            return 0
        else
            local error_detail
            error_detail="$(python3 -c "import json; data=json.load(open('$api_response')); print(data.get('detail','unknown error'))" 2>/dev/null || cat "$api_response")"
            echo "❌ Task 创建失败 (HTTP $http_status_code):"
            echo "   $error_detail"
            rm -f "$api_response"
            return 1
        fi
    else
        echo "❌ 未找到 curl 命令，无法发送 API 请求。"
        echo "   请安装 curl 后重试。"
        return 1
    fi
}

# 如果直接执行本脚本，运行 create_koda_task
if [ -n "${BASH_VERSION:-}" ] && [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    create_koda_task "$@"
fi
