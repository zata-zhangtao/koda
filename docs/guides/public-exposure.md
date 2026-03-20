# 公网暴露操作手册

## 架构概览

```
外网用户
  → Traefik（Dokploy 管理，TLS 终结）
  → Caddy 容器（Basic Auth + WebSocket 路由）
  → Gateway 容器（隧道服务端，port 9000）
    ↕ WebSocket 长连接（wss://）
本机 Agent
  → 本机 DSL 应用（http://127.0.0.1:8000）
```

所有组件均部署于 `deploy/public-forward/docker-compose.yml`，TLS 由 Dokploy 内置的 Traefik 处理，Caddy 仅负责 Basic Auth 和路由，不做 TLS。

---

## 一、服务器部署（Dokploy）

### 1. 创建 Compose 应用

在 Dokploy 中新建一个 Compose 应用，将仓库根目录作为源，Compose 文件路径填：

```
deploy/public-forward/docker-compose.yml
```

### 2. 配置环境变量

在 Dokploy 的 **Environment** 标签中填入以下变量（以实际值替换示例值）：

```env
# Basic Auth（浏览器访问时弹出的用户名/密码）
CADDY_BASICAUTH_USER=koda
CADDY_BASICAUTH_PASSWORD=your-browser-password

# 隧道鉴权（本机 agent 与 gateway 必须一致）
KODA_TUNNEL_ID=demo-tunnel
KODA_TUNNEL_SHARED_TOKEN=your-long-random-secret

# Gateway 运行参数（可保持默认）
GATEWAY_LOG_LEVEL=INFO
KODA_TUNNEL_RESPONSE_TIMEOUT_SECONDS=30
KODA_TUNNEL_HEARTBEAT_TIMEOUT_SECONDS=45
```

> **注意**：Dokploy 的 Environment 变量直接注入容器，不参与 `docker-compose.yml` 的 `${}` 插值，这是正确的设计，无需额外操作。

### 3. 配置域名

在 Dokploy 的 **Domains** 标签中添加域名，配置如下：

| 字段 | 值 |
|---|---|
| Service Name | `caddy` |
| Host | `your-domain.com` |
| Path | `/` |
| Container Port | `80` |
| HTTPS | 开启（Let's Encrypt） |

> Traefik 负责 TLS，Caddy 只监听容器内部的 80 端口。

### 4. 部署

点击 **Deploy**，等待两个容器均变为 `healthy`：

- `gateway`：Python 隧道服务端
- `caddy`：反向代理 + Basic Auth

验证服务端正常：

```bash
# 在服务器上执行，应返回 {"status":"healthy",...}
curl https://your-domain.com/_gateway/health -u your-user:your-password
```

---

## 二、本机启动

### 1. 配置本机 `.env`

参考 `deploy/public-forward/agent.env.example`，在项目根目录创建或修改 `.env`：

```env
# 必须使用 https://，否则 WebSocket 会用 ws:// 被 Traefik 拒绝
KODA_PUBLIC_BASE_URL=https://your-domain.com
KODA_TUNNEL_SERVER_URL=https://your-domain.com

# 与服务器环境变量完全一致
KODA_TUNNEL_ID=demo-tunnel
KODA_TUNNEL_SHARED_TOKEN=your-long-random-secret

# 本机 DSL 监听地址
KODA_TUNNEL_UPSTREAM_URL=http://127.0.0.1:8000
```

### 2. 构建前端

```bash
just public-build
```

### 3. 启动（一条命令）

```bash
just public-serve
```

该命令同时启动 DSL 应用（`SERVE_FRONTEND_DIST=true`）和隧道 Agent，任意一个进程退出则全部终止。

正常输出中可看到：

```json
{"event": "agent_connected", "tunnel_id": "demo-tunnel", ...}
{"event": "agent_heartbeat_ack", ...}
```

> 如需分开运行（分别查看日志），也可以：
>
> ```bash
> just public-run    # 终端 1
> just public-agent  # 终端 2
> ```

### 5. 访问

浏览器打开 `https://your-domain.com/`，输入 Basic Auth 用户名密码，即可看到 DSL 前端。

---

## 三、启动顺序

```
服务器                          本机
──────                          ────
1. Dokploy 配置环境变量
2. Dokploy 配置域名
3. Deploy（gateway + caddy）
                                4. 修改 .env（https://）
                                5. just public-build
                                6. just public-serve
                                7. 浏览器访问
```

---

## 四、常见故障排查

### agent 报 `HTTP 404` 无法连接

原因：`KODA_TUNNEL_SERVER_URL` 使用了 `http://` 而不是 `https://`，导致 WebSocket 走 `ws://`，Traefik 无法路由。

```env
# 错误
KODA_TUNNEL_SERVER_URL=http://your-domain.com

# 正确
KODA_TUNNEL_SERVER_URL=https://your-domain.com
```

### caddy 容器 unhealthy / 报 `Either CADDY_BASICAUTH_PASSWORD or CADDY_BASICAUTH_HASH must be set`

原因：Dokploy Environment 变量未保存，或未 redeploy 使其生效。

处理：确认变量已保存 → 重新 Deploy。

### 浏览器返回 `503 Tunnel Offline`

原因：caddy/gateway 正常，但本机 agent 未连接。

处理：

1. 确认本机 `just public-run` 在运行（`http://127.0.0.1:8000/health` 应返回 200）
2. 确认本机 `just public-agent` 在运行且输出 `agent_connected`
3. 确认 `KODA_TUNNEL_ID` 和 `KODA_TUNNEL_SHARED_TOKEN` 与服务器一致

### 浏览器返回 `401 Unauthorized`

原因：Basic Auth 密码错误。

处理：用 Dokploy 里配置的 `CADDY_BASICAUTH_USER` 和 `CADDY_BASICAUTH_PASSWORD` 登录。

### 本机启动报错 `frontend/dist` 不存在

原因：未执行前端构建。

```bash
just public-build
just public-run
```

---

## 五、日志定位

**服务器**（在 Dokploy Logs 标签或 SSH 执行）：

```bash
docker compose -f deploy/public-forward/docker-compose.yml logs -f gateway
docker compose -f deploy/public-forward/docker-compose.yml logs -f caddy
```

关键 gateway 事件：

| 事件 | 含义 |
|---|---|
| `tunnel_connected` | agent 已成功连接 |
| `tunnel_disconnected` | agent 断开 |
| `tunnel_auth_rejected` | token 错误 |
| `gateway_request_failed` | 请求超时或 agent 断线 |

**本机 agent** 关键事件：

| 事件 | 含义 |
|---|---|
| `agent_connected` | 连接服务器成功 |
| `agent_connection_failed` | 连接失败（含错误原因） |
| `agent_heartbeat_ack` | 隧道保活正常 |
| `agent_request_forwarded` | 请求成功转发到本机 DSL |
| `agent_upstream_failed` | 本机 DSL 无响应 |

---

## 六、边界说明

- 仅支持 HTTP/HTTPS 流量，不支持 TCP/UDP 透传。
- 单租户设计：一个 `KODA_TUNNEL_ID` 对应一个本机实例。
- 不包含 WAF、多租户隔离、高可用容灾。
- 不建议将 Vite 开发服务器（port 5173）直接暴露，始终使用 `just public-run`（`SERVE_FRONTEND_DIST=true`）。
