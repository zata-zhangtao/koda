# Codex 脚本调用

## 结论

可以。当前开发机已经在 **2026-03-17** 通过 `codex --help` 与 `codex exec --help` 验证：`codex` CLI 提供了适合脚本调用的非交互子命令 `codex exec`。

对自动化场景，最实用的组合是：

- `codex exec`：一次性执行提示词
- `--json`：把事件流以 JSONL 形式写到标准输出
- `-C <dir>`：指定工作目录
- `-o <file>`：把最后一条消息单独写入文件

## 推荐调用方式

最小命令如下：

```bash
codex exec --json -C /path/to/repo "分析这个项目的结构"
```

如果提示词很长，可以通过标准输入传入：

```bash
cat prompt.txt | codex exec --json -C /path/to/repo -
```

这里的 `-` 表示从 `stdin` 读取提示词，而不是把 `-` 当作普通字符串。

## 为什么推荐 `--json`

`--json` 让脚本可以按行处理 Codex 输出，而不是把整段终端文本当成不可解析的字符流。常见用途包括：

- 实时打印代理事件
- 把每一行 JSON 追加到日志文件
- 只提取某些事件类型做二次处理
- 在任务结束后根据退出码判断成功或失败

## Python 监听示例

下面是一个最小可用的包装器。它会启动 `codex exec`，实时读取 `stdout`，尝试按 JSON 解析，并把完整事件流保存到日志文件。

```python
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def run_codex_exec(prompt_text: str, workspace_dir: str) -> int:
    """运行 codex exec 并实时监听输出。"""

    logs_dir_path = Path("logs")
    logs_dir_path.mkdir(parents=True, exist_ok=True)
    jsonl_log_path = logs_dir_path / "codex-exec.jsonl"

    codex_process = subprocess.Popen(
        [
            "codex",
            "exec",
            "--json",
            "-C",
            workspace_dir,
            prompt_text,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    assert codex_process.stdout is not None
    assert codex_process.stderr is not None

    with jsonl_log_path.open("a", encoding="utf-8") as log_file:
        for stdout_line in codex_process.stdout:
            stripped_stdout_line = stdout_line.rstrip("\n")
            print(stripped_stdout_line)
            log_file.write(stripped_stdout_line + "\n")

            try:
                codex_event_obj = json.loads(stripped_stdout_line)
            except json.JSONDecodeError:
                continue

            event_type = codex_event_obj.get("type")
            if event_type:
                print(f"[event] {event_type}")

    stderr_text = codex_process.stderr.read()
    if stderr_text:
        print(stderr_text)

    codex_process.wait()
    return codex_process.returncode
```

## 只拿最终答案

如果你不关心中间事件，只想保留最终回答，可以额外使用 `-o`：

```bash
codex exec --json -o last_message.txt -C /path/to/repo "帮我总结这个仓库"
```

这样做的好处是：

- `stdout` 继续保留完整事件流，方便调试
- `last_message.txt` 直接保存最终消息，方便后续脚本消费

## 实践建议

- 逐行读取 `stdout`，不要等进程退出后一次性读取。
- 对日志文件显式使用 `encoding="utf-8"`。
- 依赖 `returncode` 判断任务是否成功，而不是仅靠有没有文本输出。
- 事件 JSON 的字段结构可能随 CLI 版本演进，解析时优先只依赖你真正用到的字段。

## 适用边界

`codex exec` 适合“一次发起任务，持续看输出，结束后拿结果”的模式。

如果你需要的是更长期、协议化的集成，而不是一次性任务执行，可以进一步研究 CLI 自带的 `codex mcp-server`。这一页先聚焦已经验证可用、落地成本最低的 `exec` 模式。
