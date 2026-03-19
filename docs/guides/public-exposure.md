# 公网暴露操作手册

## 目标

本手册描述如何通过“服务器 gateway + 本机 agent”的方式，把本机运行的 DSL 受控暴露到公网，而不迁移本地 SQLite、媒体目录、Git 仓库或 Codex CLI。

## 快速流程

### 服务器

```bash
cd deploy/public-forward
docker compose up -d --build
```

这里默认服务器环境变量已经由 shell / CI / systemd 注入；`deploy/public-forward/.env.example` 只作为变量清单。

### 本机

```bash
cp deploy/public-forward/agent.env.example .env
npm --prefix frontend run build
just public-run
just public-agent
```

## 运行顺序建议

1. 先准备服务器传给 `docker compose` 的环境变量
2. 启动服务器 `docker compose up -d --build`
3. 本机构建 `frontend/dist`
4. 本机启动 `just public-run`
5. 本机启动 `just public-agent`
6. 浏览器访问 `https://<KODA_PUBLIC_HOST>/`

## 正常行为

当一切正常时：

- 浏览器先看到 Basic Auth 提示框
- 认证成功后，`/` 会打开 DSL 前端页面
- 页面内 `/api/*`、`/media/*` 请求继续使用相对路径，不需要改单页应用代码
- `gateway` 日志会输出 `tunnel_connected`
- `public-agent` 日志会周期性输出 `agent_heartbeat_sent` / `agent_heartbeat_ack`

## 常见故障与恢复步骤

### 1. 浏览器返回 `401 Unauthorized`

含义：

- Caddy Basic Auth 未通过

检查：

- 服务器传给 `docker compose` 的 `CADDY_BASICAUTH_USER`
- 服务器传给 `docker compose` 的 `CADDY_BASICAUTH_PASSWORD` 或 `CADDY_BASICAUTH_HASH`

恢复：

1. 如果你用明文模式，更新 `CADDY_BASICAUTH_PASSWORD`
2. 如果你用哈希模式，重新生成 `CADDY_BASICAUTH_HASH`
3. 如果两个都设置了，确认你记住的是明文密码，因为容器会优先采用 `CADDY_BASICAUTH_PASSWORD`
4. 执行 `docker compose up -d`

### 2. 浏览器返回 `503 Tunnel Offline`

含义：

- gateway 已在线，但当前 `KODA_TUNNEL_ID` 没有活动 agent

检查：

- 本机 `just public-run` 是否仍在运行
- 本机 `just public-agent` 是否仍在运行
- 本机和服务器的 `KODA_TUNNEL_ID` 是否一致
- 本机和服务器的 `KODA_TUNNEL_SHARED_TOKEN` 是否一致

恢复：

1. 先确认本机 DSL `http://127.0.0.1:8000/health` 正常
2. 重启 `just public-agent`
3. 如仍失败，查看 `docker compose logs gateway` 与本机 agent 日志

### 3. agent 日志反复出现连接失败

含义：

- 公网域名不可达、TLS 证书未就绪，或 token 错误

检查：

- `KODA_TUNNEL_SERVER_URL` 是否指向正确域名
- `docker compose ps` 中 `caddy`、`gateway` 是否健康
- `KODA_TUNNEL_SHARED_TOKEN` 是否与服务器一致

恢复：

1. 先确认服务器 `docker compose ps`
2. 再确认 `docker compose logs gateway`
3. 修正 token / 域名后重启 `just public-agent`

### 4. 本机 DSL 启动时报错缺少 `frontend/dist`

含义：

- 你启用了 `SERVE_FRONTEND_DIST=true`，但未先构建前端

恢复：

```bash
npm --prefix frontend run build
just public-run
```

### 5. 页面能打开，但 API 或媒体资源异常

含义：

- tunnel 存在，但本机 DSL 路由或本机 upstream 不可用

检查：

- `KODA_TUNNEL_UPSTREAM_URL` 是否仍指向 `http://127.0.0.1:8000`
- 本机 `http://127.0.0.1:8000/api/...` 是否本来就正常
- 本机 `http://127.0.0.1:8000/media/...` 是否可访问

恢复：

1. 先在本机直接访问 DSL 路由
2. 修正本机 DSL 后，再观察公网入口是否恢复

## 日志定位

服务器：

```bash
cd deploy/public-forward
docker compose logs -f gateway
docker compose logs -f caddy
```

本机：

```bash
just public-run
just public-agent
```

结构化日志重点看这些事件：

- `tunnel_auth_rejected`
- `tunnel_connected`
- `tunnel_disconnected`
- `agent_connection_failed`
- `agent_heartbeat_sent`
- `agent_heartbeat_ack`
- `agent_upstream_failed`

## 恢复优先级

遇到故障时按这个顺序排查最快：

1. 先看服务器 `docker compose ps`
2. 再看 gateway 日志里是否有 `tunnel_connected`
3. 然后看本机 agent 是否在持续重连
4. 最后直接访问本机 `http://127.0.0.1:8000/health`

## 边界说明

- 本方案只覆盖当前 DSL 所需的 HTTP/HTTPS 流量。
- 不支持任意 TCP/UDP 透传。
- 不包含企业级单点登录、WAF、多租户隔离或高可用容灾。
- 不建议把 Vite 开发服务器直接长期暴露到公网。
