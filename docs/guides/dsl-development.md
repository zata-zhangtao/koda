# DSL 开发指南

## 总览

DSL 当前是一套典型的前后端分离应用：

- `frontend/`：React + Vite 前端
- `main.py`：后端启动入口
- `dsl/`：FastAPI 路由、模型、服务层
- `utils/`：日志、配置、数据库等通用底座

## 后端入口

后端启动链路如下：

1. `main.py` 调用 `uvicorn.run("dsl.app:app", ...)`
2. `dsl.app` 创建 FastAPI 应用并注册路由
3. `lifespan` 在启动时调用 `create_tables(Base)` 初始化表结构

这意味着本地首次启动时，SQLite 表会自动创建，不需要手工跑迁移。

## 路由分层

当前后端接口分为五组：

- `run_accounts`：运行账户管理
- `tasks`：任务生命周期管理
- `logs`：开发日志 CRUD 与命令解析
- `media`：图片和附件上传
- `chronicle`：时间线、任务编年史与 Markdown 导出

这一层主要负责 HTTP 参数解析、状态码和异常翻译，业务逻辑继续下沉到 `dsl/services/`。

## 数据与文件

- SQLite 数据库：`data/dsl.db`
- 原图目录：`data/media/original`
- 缩略图目录：`data/media/thumbnail`
- 应用日志：`logs/app.log`

开发时如果你看到接口返回成功但页面没有渲染媒体，通常先检查 `StaticFiles` 挂载的目录里是否已经生成文件。

## 前端协作方式

前端默认运行在 `5173` 端口，后端在 `8000` 端口。`dsl.app` 已内置本地开发需要的 CORS 配置：

- `http://localhost:5173`
- `http://127.0.0.1:5173`

如果你新增了前端调试域名，记得同步更新 CORS 配置与文档。

## 推荐开发流程

```bash
uv sync
cd frontend && npm install
cd ..
just dsl-dev
```

当你只调后端时，可以简化为：

```bash
just setup-data
uv run python main.py
```
