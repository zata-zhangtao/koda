这款软件不仅仅是一个记录工具，更像是一个 **“懂代码的开发伴侣”**，帮你把碎片化的操作自动整理成结构化的文档。

---

# 产品需求文档 (PRD): DevStream Log (智能开发流日志)

| 文档属性 | 内容 |
| --- | --- |
| **产品名称** | DevStream Log (DSL) |
| **版本号** | V2.0 (多模态智能版) |
| **最后更新** | 2026-02-09 |
| **核心理念** | Keep Flow, Log Smart. (保持心流，智能记录) |

---

## 1. 产品愿景 (Product Vision)

为开发者提供一款 **“低摩擦、高保真”** 的过程记录工具。
它允许开发者以极速（文本/截图）记录开发过程中的每一个瞬间，利用 AI 异步解析复杂的报错截图，最终将碎片化的日志自动编排成一份逻辑严密、图文并茂的 **项目编年史 (Project Chronicle)**。

---

## 2. 核心概念与逻辑 (Core Concepts)

### 2.1 四大核心实体

1. **Run Account (运行账户):** 上下文环境。如 `User:Zata @ Env:MacOS-Pro (Branch: feat/login)`.
2. **Task (任务):** 当前聚焦的工作单元。如 `修复 Qdrant 连接 502 错误`.
3. **Log (日志):** 最小原子记录。包含：文本、图片、代码片段。
4. **State (状态):** 驱动任务生命周期的关键动作（见下表）。

### 2.2 状态流转逻辑 (State Logic)

| 图标 | 状态名称 | 含义与触发动作 |
| --- | --- | --- |
| 🐛 | **Found Bug** | **动作:** 标记当前上下文出现阻碍。系统自动高亮该节点为红色。 |
| 💡 | **Optimization** | **动作:** 发现非阻塞性改进点。系统将其标记为黄色，并可一键加入 "Backlog"。 |
| ✅ | **Fixed** | **动作:** 问题解决。系统自动计算从“发现Bug”到“修复”的耗时，并将关联 Task 标记为完成。 |
| ⏭️ | **Transferred** | **动作:** 责任转移。记录“移交给谁/哪个部门”，关联 Task 挂起或关闭。 |

---

## 3. 功能需求详情 (Functional Requirements)

### 3.1 核心输入模块 (The Stream Input)

* **超级输入框:**
* 支持 Markdown 语法。
* **混合输入:** 支持文字与图片混排（直接 `Ctrl+V` 粘贴截图）。
* **指令驱动:** 输入 `/bug` 自动切换状态，输入 `/task` 切换任务。


* **极速响应:** 图片粘贴后，立即在本地显示缩略图，**不阻塞**用户继续输入下一行代码或日志。

### 3.2 智能视觉解析 (AI Vision & Async Processing)

这是产品的核心差异化功能。

* **触发机制:** 当用户上传图片（报错截图、终端日志、AI 对话截图）时，后台静默启动 AI 解析任务。
* **AI 解析目标:**
1. **摘要 (Summary):** 图片里发生了什么？（例：`PyTorch CUDA 版本不匹配`）
2. **根因 (Root Cause):** 如果图中有分析过程，提取核心原因。
3. **代码提取 (OCR & Formatting):** 将图中的修复命令或代码提取为可复制的文本块。


* **状态标记:**
* `⏳ Analyzing`: AI 正在后台跑。
* `🔔 Review Needed`: AI 跑完了，等待用户确认（如果置信度低）。
* `✔ Verified`: 用户已确认或系统高置信度自动确认。



### 3.3 异步“待办校正”队列 (Review Queue)

* **痛点解决:** 防止 AI 解析慢打断用户思路。用户只管截图，有空再来确认。
* **交互:** 侧边栏显示 `🔔 待校正 (3)`。
* **校正界面:**
* 左侧：原始大图。
* 右侧：AI 填写的表单（标题、描述、提取的代码）。
* 操作：`Accept (接受)` / `Edit (微调)` / `Retry (重试)`。



### 3.4 最终产物：项目编年史 (The Chronicle Documentation)

这是用户最终看到的“文档效果”。系统根据时间轴和任务，将碎片日志渲染成文档。

* **视图模式:**
* **按时间 (Timeline):** 今天的流水账。
* **按任务 (Task View):** 一个任务从生到死的完整过程（最常用）。


* **渲染逻辑 (Markdown 示例):**

```markdown
# 任务：解决 Qdrant 本地连接失败

### [15:50] 🐛 发现问题
**现象:** Python 客户端报错 `Connection Refused`。
> (此处展示原始报错截图缩略图，点击放大)

### [16:05] 💡 排查过程 (AI 辅助记录)
**分析:** 根据 AI 对话截图分析，原因是 macOS 的 Clash 代理拦截了 localhost 流量。
**证据:**
> (此处展示包含 AI 对话的长截图)

### [16:15] ✅ 解决方案
**操作:** 在代码中强制关闭代理。
**代码:**
```python
# 代码由图片自动提取
import os
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

```

---

```

---

## 4. 界面原型设计 (UI Layout)

### 4.1 主界面 (3栏布局)
1.  **左栏 (Context & Queue):**
    * 顶部：当前 Run Account (头像+环境)。
    * 中部：活跃任务列表 (Active Tasks)。
    * 底部：**待校正通知 (Review Queue)** —— *醒目的红点提示*。
2.  **中栏 (The Stream):**
    * 类似微信/Slack 的对话流。
    * **卡片式日志:**
        * 普通文本是气泡。
        * 图片日志是一个带有状态指示灯（⏳/🔔/✔）的卡片。
        * 状态日志（Bug/Fix）带有鲜艳的左侧边框颜色（红/绿）。
3.  **底栏 (Input):**
    * 输入框 + 4个状态快捷按钮。

### 4.2 校正弹窗 (Review Modal)
* 设计为“快速过单”模式。
* 快捷键：`Enter` 确认下一张，`Esc` 跳过。

---

## 5. 数据模型设计 (Data Schema)

为了支持上述功能，数据库设计如下（TypeScript Interface 示意）：

```typescript
// 1. 日志实体
interface DevLog {
  id: string;
  task_id: string;
  run_account_id: string;
  timestamp: number;
  
  // 核心内容
  text_content: string; // 用户手写的备注
  
  // 状态标记
  state_tag: 'NONE' | 'BUG' | 'OPTIMIZATION' | 'FIXED' | 'TRANSFERRED';
  
  // 图片与AI增强 (重点)
  media?: {
    original_image_path: string; // 本地存储路径
    ai_status: 'PENDING' | 'PROCESSING' | 'WAITING_REVIEW' | 'CONFIRMED';
    
    // AI 解析结果 (作为 Draft 存在，确认后合并显示)
    ai_generated_title?: string;  // 例如 "Qdrant 502 Error"
    ai_analysis_text?: string;    // 例如 "代理配置错误导致..."
    ai_extracted_code?: string;   // 提取的代码块
  };
}

// 2. 任务实体
interface Task {
  id: string;
  title: string;
  status: 'OPEN' | 'CLOSED' | 'PENDING';
  logs: DevLog[]; // 关联的日志集合
}

```

---

## 6. 技术实现路径建议 (Technical Stack)

由于涉及到本地文件操作（截图）和系统级快捷键，建议使用：

* **框架:** **Tauri** (Rust + React/Vue) 或 **Electron**。Tauri 更轻量，符合“极速”要求。
* **数据库:** **SQLite** (本地存储，无需联网也可记录)。
* **AI 能力:**
* **方案 A (云端):** 调用 OpenAI GPT-4o 或 Gemini 1.5 Pro API (多模态能力强)。
* **方案 B (本地隐私):** 如果用户电脑配置高，可对接 Ollama (Llava / BakLLaVA 模型) 进行本地图片解析。



---

## 7. 交互流程故事 (User Story)

1. **Bug 出现:** 开发小王正在写代码，突然报错。他按下快捷键呼出 DevStream。
2. **截图录入:** 他用系统截图工具截取了报错信息，`Ctrl+V` 粘贴进输入框，打了标签 `#bug`，回车。
* *系统:* 立即显示日志，后台开始上传图片给 AI。


3. **排查:** 小王去问 ChatGPT，ChatGPT 给了个方案。
4. **记录方案:** 小王把 ChatGPT 的回答长截图，再次粘贴进 DevStream，输入“AI 建议的方案”，回车。
5. **解决:** 小王修改代码，测试通过。他在 DevStream 输入“搞定，代理问题”，点击 `✅ Fixed`。
6. **事后回顾 (Next Launch):**
* 第二天早上，小王打开软件。
* 侧边栏提示 `🔔 2条图片待校正`。
* 他点开，看到 AI 已经把第一张图识别为 `Connection Error`，第二张图提取出了 `export NO_PROXY` 代码。
* 他点击“确认”。


7. **输出:** 他点击“导出 Markdown”，一份包含完整排错路径和代码片段的技术文档生成了。

---

### 你觉得这个 PRD 是否完整？下一步你是想先看**核心数据结构的 SQL 代码**，还是想看 **Electron/Tauri 的部分实现代码**？