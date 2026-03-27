# 配置说明

## 总览

Koda 现在有三类关键配置：

1. **DSL 本体配置**
   由 `utils/settings.py` 和根目录 `.env` 驱动。
2. **本机 agent 配置**
   使用和 DSL 相同的环境变量名，重点是 `KODA_TUNNEL_*`。
3. **服务器公网入口配置**
   由外部注入的环境变量驱动 `docker compose`、Caddy 和 gateway；`deploy/public-forward/.env.example` 仅作变量清单。

## 配置文件清单

| 位置 | 作用 | 关键内容 |
| --- | --- | --- |
| `pyproject.toml` | Python 依赖定义 | FastAPI、SQLAlchemy、httpx、websockets、MkDocs、Pytest |
| `justfile` | 命令入口 | `dsl-dev`、`public-build`、`public-run`、`public-agent` |
| `utils/settings.py` | DSL 运行配置 | 日志、数据库、应用时区、媒体目录、目录/终端启动器模板、`SERVE_FRONTEND_DIST`、`KODA_TUNNEL_*`、`TASK_QA_*` |
| `.env.example` | 本机 DSL / agent 样例 | 开发安全默认值，保留可选 public 参数与 sidecar Q&A 默认策略 |
| `deploy/public-forward/.env.example` | 服务器样例 | 域名、Basic Auth、gateway 参数 |
| `deploy/public-forward/agent.env.example` | 本机公网模式样例 | 便于单独复制到开发机 |
| `frontend/vite.config.ts` | 前端开发服务器配置 | 默认端口 `5173`、`/api` 与 `/media` 代理 |
| `mkdocs.yml` | 文档站点配置 | 导航、插件、Mermaid 支持 |

## DSL 运行配置

`utils/settings.py` 通过 `load_dotenv()` 读取根目录 `.env`，然后暴露 `Config` 类。

### DSL / 本机 agent 关键配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Python 日志级别 |
| `APP_NAME` | `app` | 日志记录器名称 |
| `APP_TIMEZONE` | `Asia/Shanghai` | 应用展示时区 |
| `KODA_AUTOMATION_RUNNER` | `codex` | 任务自动化执行器类型（`codex` / `claude`） |
| `DATABASE_URL` | `sqlite:///.../data/dsl.db` | 默认 SQLite 数据库 |
| `MEDIA_STORAGE_PATH` | `<repo>/data/media` | 图片与附件目录 |
| `AI_CONFIDENCE_THRESHOLD` | `0.85` | AI 解析置信度阈值预留值 |
| `KODA_OPEN_PATH_COMMAND_TEMPLATE` | `trae-cn {target_path_shell}` | 覆盖“打开项目目录 / Worktree”按钮命令模板 |
| `TASK_QA_BACKEND` | `chat_model` | 任务内独立问答后端；首版固定走 `model_loader` 聊天模型工具层 |
| `TASK_QA_MODEL_NAME` | `qwen-plus` | 任务内独立问答使用的聊天模型名 |
| `TASK_QA_MODEL_TEMPERATURE` | `0.0` | 任务内独立问答聊天模型温度 |
| `KODA_OPEN_TERMINAL_COMMAND` | 未设置 | 覆盖“打开终端”按钮命令模板 |
| `SERVE_FRONTEND_DIST` | `false` | 是否由 FastAPI 同源托管 `frontend/dist` |
| `FRONTEND_DIST_PATH` | `<repo>/frontend/dist` | 打包前端目录 |
| `KODA_PUBLIC_BASE_URL` | 未设置 | 远程浏览器访问的公网 URL |
| `KODA_TUNNEL_SERVER_URL` | `ws://127.0.0.1:9000` | agent 连接的 gateway 基础地址 |
| `KODA_TUNNEL_ID` | `default` | 单租户 tunnel 标识 |
| `KODA_TUNNEL_SHARED_TOKEN` | 空字符串 | agent 与 gateway 共用 token |
| `KODA_TUNNEL_UPSTREAM_URL` | `http://127.0.0.1:8000` | agent 转发目标 |
| `SCHEDULER_ENABLE` | `true` | 是否启用任务调度轮询器 |
| `SCHEDULER_POLL_INTERVAL_SECONDS` | `30` | 调度轮询间隔（秒） |
| `SCHEDULER_MAX_DISPATCH_PER_TICK` | `20` | 每轮最多分发的到期规则数量 |

### 目录打开命令模板

`KODA_OPEN_PATH_COMMAND_TEMPLATE` 控制前端“打开项目目录”和“打开 Worktree”按钮调用的本地命令。

示例：

```bash
KODA_OPEN_PATH_COMMAND_TEMPLATE='code {target_path_shell}'
KODA_OPEN_PATH_COMMAND_TEMPLATE='cursor --reuse-window {target_path_shell}'
KODA_OPEN_PATH_COMMAND_TEMPLATE='trae-cn {target_path_shell}'
```

可用占位符：

| 占位符 | 说明 |
| --- | --- |
| `{target_path}` | 原始目录路径 |
| `{target_path_shell}` | Shell 转义后的目录路径 |
| `{target_kind}` | 当前目标类型，取值为 `project` 或 `worktree` |

注意点：

- 默认值仍然是 `trae-cn {target_path_shell}`，因此老用户不改配置时行为保持兼容。
- 若模板包含未知占位符、渲染为空命令或可执行文件不存在，后端会返回可诊断错误信息。
- 建议优先使用 `{target_path_shell}`，避免目录路径包含空格时触发命令解析问题。

### 本机 agent 可选调优项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `KODA_TUNNEL_HEARTBEAT_INTERVAL_SECONDS` | `15` | agent 心跳发送周期 |
| `KODA_TUNNEL_REQUEST_TIMEOUT_SECONDS` | `30` | agent 等待 gateway 请求/ack 的超时 |
| `KODA_TUNNEL_RECONNECT_DELAY_SECONDS` | `2` | 初始重连等待 |
| `KODA_TUNNEL_MAX_RECONNECT_DELAY_SECONDS` | `15` | 指数退避上限 |
| `KODA_TUNNEL_OPEN_TIMEOUT_SECONDS` | `10` | 初始 WebSocket 建连超时 |
| `KODA_TUNNEL_AGENT_LOG_LEVEL` | `INFO` | agent 结构化日志级别 |

### 注意点

- `SERVE_FRONTEND_DIST=true` 时，`dsl/app.py` 会要求 `FRONTEND_DIST_PATH/index.html` 存在；如果未先构建前端，会直接失败并提示重新执行 `npm --prefix frontend run build`。
- `just dsl-dev` 不依赖上述打包参数，仍然使用 Vite 开发服务器。
- 调度器是单实例轮询模型；若暂不需要自动触发，可把 `SCHEDULER_ENABLE` 设为 `false`。
- 根目录 `.env.example` 故意保持 `SERVE_FRONTEND_DIST=false`；如果要直接套用公网打包模式，请复制 `deploy/public-forward/agent.env.example`。
- 根目录 `.env.example` 也保留了 `KODA_OPEN_PATH_COMMAND_TEMPLATE=trae-cn {target_path_shell}` 的本地默认值；如果你使用其他编辑器，请按本机命令覆盖。
- sidecar Q&A 首版固定走 `TASK_QA_BACKEND=chat_model`，以复用 `ai_agent/utils/model_loader.py` 的模型与凭据管理能力，同时保持它与主 Codex 执行链路解耦。
- 前端启动时会请求只读接口 `/api/app-config`，继续用它同步 `APP_TIMEZONE`。
- 根目录 `.env.example` 适合本机 DSL / agent；服务器不要直接复用这个文件。
- `KODA_AUTOMATION_RUNNER` 若配置为非法值，后端会在启动时直接失败并提示可用值。

## 服务器公网入口配置

服务器侧由外部环境变量驱动；`deploy/public-forward/.env.example` 只作为示例与核对清单。

### 服务器关键配置项

| 配置项 | 说明 |
| --- | --- |
| `KODA_PUBLIC_HOST` | 公网域名，例如 `koda.example.com` |
| `CADDY_ACME_EMAIL` | Caddy 自动申请证书使用的邮箱 |
| `CADDY_BASICAUTH_USER` | 浏览器侧 Basic Auth 用户名 |
| `CADDY_BASICAUTH_PASSWORD` | 浏览器侧 Basic Auth 明文密码；容器启动时自动转成 Caddy 哈希 |
| `CADDY_BASICAUTH_HASH` | 可选的 Caddy `basicauth` 哈希密码；仅在未提供明文密码时使用 |
| `KODA_TUNNEL_ID` | gateway 对外公开转发的 tunnel id |
| `KODA_TUNNEL_SHARED_TOKEN` | 与本机 agent 一致的共享 token |
| `GATEWAY_LOG_LEVEL` | gateway 结构化日志级别 |
| `KODA_TUNNEL_RESPONSE_TIMEOUT_SECONDS` | gateway 等待 agent 响应的超时 |
| `KODA_TUNNEL_HEARTBEAT_TIMEOUT_SECONDS` | gateway 认定 tunnel 失活的超时 |

### 注意点

- `docker-compose.yml` 会显式把 gateway / caddy 所需变量透传进容器；如果缺少 `KODA_PUBLIC_HOST`、`CADDY_ACME_EMAIL`、`CADDY_BASICAUTH_USER`、`KODA_TUNNEL_ID` 或 `KODA_TUNNEL_SHARED_TOKEN`，`docker compose` 会在渲染阶段直接失败。
- `caddy` 容器要求 `CADDY_BASICAUTH_PASSWORD` 或 `CADDY_BASICAUTH_HASH` 至少提供一个；如果两者都为空，容器会在启动时直接退出。
- 如果同时设置 `CADDY_BASICAUTH_PASSWORD` 和 `CADDY_BASICAUTH_HASH`，容器会优先使用明文密码并在启动时重新生成哈希。
- `KODA_TUNNEL_ID` 和 `KODA_TUNNEL_SHARED_TOKEN` 必须和本机 agent 完全一致。
- `gateway` 和 `agent` 都会拒绝空值或示例占位 token；上线前必须把 `.env.example` 里的占位串替换成真实随机密钥。
- `Caddyfile` 会放行 `/ws/tunnels/*` 给 agent 建连，但所有浏览器路径默认都要通过 Basic Auth。
- `gateway` 的内部健康检查走 `/_gateway/health`，不是对外 DSL 的 `/health`。

## 前端开发配置

`frontend/vite.config.ts` 依然约定：

- 默认开发端口为 `5173`
- 默认把 `/api` 代理到 `http://localhost:8000`
- 默认把 `/media` 代理到 `http://localhost:8000`
- 构建产物输出到 `frontend/dist`

当你使用 `just dsl-dev backend_port=... frontend_port=...` 时：

- `justfile` 会把 `frontend_port` 传给 Vite
- `/api` 与 `/media` 的代理目标会自动跟随后端端口
- 后端 CORS 白名单也会同步放行当前前端端口

这和公网模式并不冲突：

- 开发态继续走 Vite
- 公网态先构建 `frontend/dist`，再由 FastAPI 同源托管

## 命令入口

| 命令 | 作用 |
| --- | --- |
| `just dsl-dev [backend_port=...] [frontend_port=...]` | 启动本地开发环境（后端 + Vite） |
| `just build-frontend` | 构建前端 |
| `just public-build` | 构建公网模式前端 |
| `just public-run` | 启动 `SERVE_FRONTEND_DIST=true` 的 DSL |
| `just public-agent` | 启动本机隧道 agent |
| `just docs-build` | 严格构建文档 |

## 配置变更建议

### 修改公网访问参数时

至少同步检查：

1. 根目录 `.env`
2. 服务器注入到 `deploy/public-forward/docker-compose.yml` 的环境变量
3. 本页和[公网暴露操作手册](./public-exposure.md)

### 修改端口时

至少同步检查：

1. `frontend/vite.config.ts`
2. `dsl/app.py` 的 CORS 白名单
3. `justfile`
4. `deploy/public-forward/docker-compose.yml`
5. 本页和[部署说明](./deployment.md)
