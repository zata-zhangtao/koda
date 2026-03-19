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
| `utils/settings.py` | DSL 运行配置 | 日志、数据库、应用时区、媒体目录、`SERVE_FRONTEND_DIST`、`KODA_TUNNEL_*` |
| `.env.example` | 本机 DSL / agent 样例 | 开发安全默认值，保留可选 public 参数 |
| `deploy/public-forward/.env.example` | 服务器样例 | 域名、Basic Auth、gateway 参数 |
| `deploy/public-forward/agent.env.example` | 本机公网模式样例 | 便于单独复制到开发机 |
| `frontend/vite.config.ts` | 前端开发服务器配置 | 端口 `5173`、`/api` 与 `/media` 代理 |
| `mkdocs.yml` | 文档站点配置 | 导航、插件、Mermaid 支持 |

## DSL 运行配置

`utils/settings.py` 通过 `load_dotenv()` 读取根目录 `.env`，然后暴露 `Config` 类。

### DSL / 本机 agent 关键配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Python 日志级别 |
| `APP_NAME` | `app` | 日志记录器名称 |
| `APP_TIMEZONE` | `Asia/Shanghai` | 应用展示时区 |
| `DATABASE_URL` | `sqlite:///.../data/dsl.db` | 默认 SQLite 数据库 |
| `MEDIA_STORAGE_PATH` | `<repo>/data/media` | 图片与附件目录 |
| `AI_CONFIDENCE_THRESHOLD` | `0.85` | AI 解析置信度阈值预留值 |
| `KODA_OPEN_TERMINAL_COMMAND` | 未设置 | 覆盖“打开终端”按钮命令模板 |
| `SERVE_FRONTEND_DIST` | `false` | 是否由 FastAPI 同源托管 `frontend/dist` |
| `FRONTEND_DIST_PATH` | `<repo>/frontend/dist` | 打包前端目录 |
| `KODA_PUBLIC_BASE_URL` | 未设置 | 远程浏览器访问的公网 URL |
| `KODA_TUNNEL_SERVER_URL` | `ws://127.0.0.1:9000` | agent 连接的 gateway 基础地址 |
| `KODA_TUNNEL_ID` | `default` | 单租户 tunnel 标识 |
| `KODA_TUNNEL_SHARED_TOKEN` | 空字符串 | agent 与 gateway 共用 token |
| `KODA_TUNNEL_UPSTREAM_URL` | `http://127.0.0.1:8000` | agent 转发目标 |

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
- 根目录 `.env.example` 故意保持 `SERVE_FRONTEND_DIST=false`；如果要直接套用公网打包模式，请复制 `deploy/public-forward/agent.env.example`。
- 前端启动时会请求只读接口 `/api/app-config`，继续用它同步 `APP_TIMEZONE`。
- 根目录 `.env.example` 适合本机 DSL / agent；服务器不要直接复用这个文件。

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

- 开发端口固定为 `5173`
- `/api` 代理到 `http://localhost:8000`
- `/media` 代理到 `http://localhost:8000`
- 构建产物输出到 `frontend/dist`

这和公网模式并不冲突：

- 开发态继续走 Vite
- 公网态先构建 `frontend/dist`，再由 FastAPI 同源托管

## 命令入口

| 命令 | 作用 |
| --- | --- |
| `just dsl-dev` | 启动本地开发环境（后端 + Vite） |
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
3. `deploy/public-forward/docker-compose.yml`
4. 本页和[部署说明](./deployment.md)
