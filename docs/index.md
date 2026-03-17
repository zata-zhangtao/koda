# Koda 文档

## 项目目标

Koda 当前以 **DevStream Log (DSL)** 为核心：它把开发过程中的任务、日志、媒体附件和导出能力整合为一个低摩擦记录系统。仓库同时保留了一组可复用的 AI 工具模块，方便后续接入模型配置、分析流程和自动化脚本。

这套文档的目标有两个：

- 让新开发者可以在本地快速启动 DSL 前后端。
- 把仓库内已经验证过的自动化实践固化下来，尤其是如何从脚本调用 `codex` 并实时观察输出。
- 把产品目标路线沉淀成可讨论、可迭代的文档，而不是只停留在口头描述。

## 核心特性

- **DSL Web 应用**：FastAPI 后端配合 React + Vite 前端，面向开发日志采集、任务管理和导出场景。
- **结构化数据模型**：`RunAccount`、`Task`、`DevLog` 三个核心实体构成任务和日志主链路。
- **媒体处理能力**：支持图片上传、缩略图生成和静态文件访问。
- **AI 工具模块**：`ai_agent/utils/model_loader.py` 负责加载模型清单与环境变量配置。
- **Codex 自动化实践**：仓库文档中补充了 `codex exec` 的非交互调用方式与脚本监听模式。
- **自动化研发路线**：文档已收录“技术路线 20260317”，定义从需求卡片到 PR、验收和反馈回环的目标流程。

## 快速安装

```bash
uv sync
cd frontend && npm install
cd ..
just dsl-dev
```

启动后可访问：

- 前端：`http://localhost:5173`
- 后端健康检查：`http://localhost:8000/health`

## 阅读路径

- 首次接手项目：先看[快速开始](getting-started.md)
- 需要理解运行链路：看[系统设计](architecture/system-design.md)
- 需要理解产品目标流程：看[技术路线 20260317](architecture/technical-route-20260317.md)
- 需要调用 Codex CLI：看[Codex 脚本调用](guides/codex-cli-automation.md)
- 需要查 Python 对象签名：看[API 参考](api/references.md)

## 文档维护约定

- 业务逻辑、函数签名或配置发生变化时，要同步更新 `docs/` 和 `mkdocs.yml`。
- 本仓库使用 MkDocs Material，预览命令是 `just docs-serve`。
- 提交前至少执行一次 `just docs-build`，确保站点可以在严格模式下构建通过。
