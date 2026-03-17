# AI 资产

## 当前已存在的 AI 相关资产

仓库里已经有一组独立于 DSL 主流程的 AI 工具文件，主要位于 `ai_agent/`：

- `ai_agent/utils/model_loader.py`
- `ai_agent/utils/models.json`
- `ai_agent/.env.example`

它们的职责并不是直接提供一个完整 AI Agent，而是为后续接入模型能力提供基础设施。

## 模型配置加载

`ai_agent/utils/model_loader.py` 负责三件事：

- 读取 `models.json` 中定义的提供商和模型元数据
- 从环境变量中解析 API Key
- 根据模型名推测上游提供商，并实例化 LangChain 聊天模型

这部分适合被更上层的 Agent、工作流或测试脚本复用。

## 环境变量

`ai_agent/.env.example` 当前列出了外部服务密钥的占位变量。真实密钥不应提交到仓库，而应放在本地 `.env` 或安全的密钥管理系统中。

如果你后续新增提供商，建议同时更新：

1. `ai_agent/utils/models.json`
2. `.env.example`
3. 本页文档

## 当前缺口

这次文档扫描里，没有发现已经正式收敛到仓库主线的以下资产：

- 统一的 Prompt 目录
- Golden dataset 或自动化评测脚本
- 面向生产环境的模型路由策略文档

因此后续如果开始引入完整 AI 流程，建议新增两类页面：

- Prompt 管理
- Evaluation 与回归验证

当前文档先记录已经存在且可复用的基础设施，避免把尚未落地的 AI 流程写成既定事实。
