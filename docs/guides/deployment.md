# 部署说明

## 总览

当前仓库现在有两种明确运行形态：

1. **本地开发模式**
   使用 `just dsl-dev`，默认后端跑在 `:8000`、前端使用 Vite `:5173` 代理；如有需要，也可以手动改端口。
2. **公网暴露模式**
   本机继续运行 DSL 和 Codex CLI，公网服务器只部署 `caddy + gateway`，由本机 `public-agent` 主动连出形成反向 HTTP 隧道。

这意味着本次补齐的是“受控公网入口”，不是把 SQLite、媒体目录、Git 仓库或 Codex CLI 迁移到服务器。

## 当前公网拓扑

```mermaid
flowchart LR
    Browser[Browser] --> HTTPS[HTTPS Domain]
    HTTPS --> Caddy[Caddy Basic Auth + TLS]
    Caddy --> Gateway[Public Gateway]
    Gateway -->|WebSocket request envelope| Agent[Local public-agent]
    Agent --> DSL[Local DSL FastAPI :8000]
    DSL --> API[/api/*]
    DSL --> MEDIA[/media/*]
    DSL --> DIST[frontend/dist]
```

## 交付件

公网模式相关资产现在位于以下位置：

| 位置 | 作用 |
| --- | --- |
| `forwarding_service/server/` | 服务器侧 gateway，负责 tunnel 注册、会话替换、离线 503 和 HTTP 转发 |
| `forwarding_service/agent/` | 本机 agent，负责心跳、重连和转发到 `KODA_TUNNEL_UPSTREAM_URL` |
| `deploy/public-forward/Dockerfile.gateway` | gateway 容器镜像构建文件 |
| `deploy/public-forward/docker-compose.yml` | 服务器 `caddy + gateway` 编排 |
| `deploy/public-forward/Caddyfile` | TLS 与 Basic Auth 配置 |
| `deploy/public-forward/.env.example` | 服务器环境变量样例 |
| `deploy/public-forward/agent.env.example` | 本机 agent / DSL 公网模式环境变量样例 |

## 本地开发模式

开发流保持不变：

```bash
uv sync
cd frontend && npm install && cd ..
just dsl-dev
```

该模式下：

- 前端默认使用 Vite `:5173`
- `/api` 与 `/media` 默认代理到 `http://localhost:8000`
- 不需要 `frontend/dist`
- 不需要 `public-agent`

如果本机端口有冲突，也可以这样启动：

```bash
just dsl-dev backend_port=8100 frontend_port=5174
```

## 公网暴露模式

### 1. 服务器部署

在服务器上：

```bash
cd deploy/public-forward
docker compose up -d --build
```

要求先由 shell / CI / systemd 注入这些环境变量：

- `KODA_PUBLIC_HOST`
- `CADDY_ACME_EMAIL`
- `CADDY_BASICAUTH_USER`
- `CADDY_BASICAUTH_PASSWORD`
- `KODA_TUNNEL_ID`
- `KODA_TUNNEL_SHARED_TOKEN`

可选兼容项：

- `CADDY_BASICAUTH_HASH`

说明：

- `deploy/public-forward/.env.example` 仅作为变量清单与示例值。
- `docker-compose.yml` 会在缺少 `KODA_PUBLIC_HOST`、`CADDY_ACME_EMAIL`、`CADDY_BASICAUTH_USER`、`KODA_TUNNEL_ID` 或 `KODA_TUNNEL_SHARED_TOKEN` 时直接报错。
- `caddy` 容器会在启动时把 `CADDY_BASICAUTH_PASSWORD` 自动转换成 Caddy 需要的哈希格式。
- 如果你同时提供 `CADDY_BASICAUTH_PASSWORD` 和 `CADDY_BASICAUTH_HASH`，会优先使用明文密码。
- 如果 `CADDY_BASICAUTH_PASSWORD` 和 `CADDY_BASICAUTH_HASH` 都没提供，`caddy` 容器会立即启动失败。

部署后：

- `caddy` 监听 `80/443`
- `gateway` 只暴露在 Compose 内部网络，健康检查走 `/_gateway/health`
- 浏览器请求默认先经过 Basic Auth
- `gateway` 在没有活动 tunnel 时返回 `503 Tunnel Offline`

### 2. 本机 DSL 打包运行

在本机开发机上：

```bash
cp .env.example .env
npm --prefix frontend run build
just public-run
```

这里复制根 `.env.example` 只是为了复用本机常规配置；该样例默认保持 `SERVE_FRONTEND_DIST=false`，不会影响 `just dsl-dev`。`just public-run` 会在启动时显式设置 `SERVE_FRONTEND_DIST=true`，让 FastAPI 同源托管：

- `/`
- `frontend/dist` 内静态资源
- SPA fallback
- `/api/*`
- `/media/*`
- `/health`

### 3. 本机 agent 连接

在同一台本机开发机上：

```bash
cp deploy/public-forward/agent.env.example .env
just public-agent
```

要求：

- `KODA_TUNNEL_ID` 必须与服务器注入给 `docker compose` 的值一致
- `KODA_TUNNEL_SHARED_TOKEN` 必须与服务器注入给 `docker compose` 的值一致
- `KODA_TUNNEL_SHARED_TOKEN` 不能保留示例占位值；`gateway` 与 `agent` 都会在启动时拒绝这类配置
- `KODA_TUNNEL_SERVER_URL` 应填写公网域名，例如 `https://koda.example.com`
- `KODA_TUNNEL_UPSTREAM_URL` 默认就是本机 DSL 的 `http://127.0.0.1:8000`

## 验证清单

服务器侧：

- `docker compose ps` 中 `caddy` 与 `gateway` 都是 `healthy` / `running`
- `docker compose logs gateway` 能看到 `tunnel_connected` / `tunnel_disconnected` 结构化日志
- 未带 Basic Auth 的浏览器请求返回 `401`

本机侧：

- `npm --prefix frontend run build` 成功产出 `frontend/dist`
- `SERVE_FRONTEND_DIST=true uv run python main.py` 时，`http://127.0.0.1:8000/` 返回前端页面
- `uv run python -m forwarding_service.agent.main` 能在 10 秒内建立 tunnel

端到端：

- 访问 `https://<your-domain>/` 可打开 DSL 页面
- 页面内 `/api/*` 请求不需要改前端代码即可工作
- `/media/*` 可以在同一域名下访问
- agent 停止后，公网入口对 `/`、`/api/*`、`/media/*`、`/health` 都返回 `503 Tunnel Offline`

## 安全边界

- 入口安全默认由 Caddy Basic Auth 提供，防止匿名浏览器流量进入 gateway。
- agent 注册安全由 `KODA_TUNNEL_SHARED_TOKEN` 提供。
- gateway 只转发当前 DSL 所需的 HTTP/HTTPS 流量，不提供任意 TCP/UDP 隧道。
- 本方案不是多租户 SaaS，不包含应用内 RBAC、OIDC、WAF 或高可用容灾。

## 容器运行注意事项

- `deploy/public-forward/Dockerfile.gateway` 使用多阶段构建，只携带 `forwarding_service` 运行所需代码。
- gateway 容器以非 root 用户运行。
- `.dockerignore` 会排除 `data/`、`logs/`、`frontend/node_modules/`、`frontend/dist/` 等本地文件。
- 如果你仍然想预先生成 Basic Auth 哈希而不是传明文密码，可运行：

```bash
docker run --rm caddy:2.8-alpine caddy hash-password --plaintext 'your-password'
```
