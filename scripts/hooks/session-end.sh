#!/usr/bin/env bash
# Stop hook: persist session summary after each Claude response.
# Reads the transcript path from stdin JSON, extracts key info,
# and appends a lightweight summary to the current session file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SESSIONS_DIR="$REPO_ROOT/.claude/planning/sessions"

# Read stdin JSON to get transcript path
input=$(cat)
transcript_path=$(echo "$input" | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get("transcript_path", ""))
except:
    print("")
' 2>/dev/null || echo "")

# Generate session ID for today
today=$(date +%Y%m%d)
session_id="${today}-$(date +%H%M%S)-koda"
session_file="$SESSIONS_DIR/.session-${today}.tmp"

# Create sessions dir if needed
mkdir -p "$SESSIONS_DIR"

# Extract summary from transcript if available
summary=""
if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
    summary=$(python3 -c "
import json, sys, os

transcript_path = '$transcript_path'
if not os.path.exists(transcript_path):
    sys.exit(0)

user_messages = []
tools_used = set()
files_modified = set()

with open(transcript_path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except:
            continue

        # Extract user messages
        if entry.get('role') == 'user':
            content = entry.get('content', '')
            if isinstance(content, str) and len(content) > 5:
                user_messages.append(content[:150])
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '')
                        if len(text) > 5:
                            user_messages.append(text[:150])

        # Extract tool usage
        if entry.get('role') == 'assistant':
            content = entry.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tools_used.add(block.get('name', 'unknown'))
                        inp = block.get('input', {})
                        # Track file modifications
                        if block.get('name') in ('Write', 'Edit'):
                            fp = inp.get('file_path', '')
                            if fp:
                                files_modified.add(fp)

output_parts = []
if user_messages:
    output_parts.append('User messages (last 5):')
    for msg in user_messages[-5:]:
        output_parts.append(f'  - {msg}')
if tools_used:
    output_parts.append(f'Tools used: {\", \".join(sorted(tools_used)[:15])}')
if files_modified:
    output_parts.append('Files modified:')
    for fp in sorted(files_modified)[:20]:
        output_parts.append(f'  - {fp}')

print('\n'.join(output_parts))
" 2>/dev/null || echo "")
fi

# Write/update session temp file
{
    # Header (only if file is new)
    if [ ! -f "$session_file" ]; then
        echo "# Session Summary: $(date +%Y-%m-%d)"
        echo "- Project: koda"
        echo "- Branch: $(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'unknown')"
        echo "- Working dir: $REPO_ROOT"
        echo "- Created: $(date '+%Y-%m-%d %H:%M:%S %z')"
        echo ""
    fi

    # Append update block
    echo "---"
    echo "### Update at $(date '+%H:%M:%S %z')"
    if [ -n "$summary" ]; then
        echo "$summary"
    else
        echo "(no transcript data available)"
    fi
    echo ""
} >> "$session_file"

# Output empty result (non-blocking)
echo '{"result": ""}'
