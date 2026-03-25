# PRD：Requirement 创建与编辑支持图片和视频输入

**原始需求标题**：`Describe what you want to build...` 输入框也要能输入图片
**需求名称（AI 归纳）**：Requirement 创建与编辑支持图片和视频输入
**文件路径**：`tasks/20260325-105411-prd-create-requirement-image-input.md`
**创建时间**：2026-03-25 10:54:11 CST
**参考上下文**：`frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/api/client.ts`, `dsl/api/media.py`, `dsl/services/media_service.py`

---

## 1. Introduction & Goals

### 背景

当前应用里只有已创建任务的反馈输入框支持粘贴或选择附件。用户在“Create Requirement”弹窗中填写新需求时，描述输入框只能输入纯文本；进入 Requirement Revision 后，编辑摘要也同样不支持图片或视频。这与已有的反馈体验不一致，也会阻断“先贴图/贴视频再建任务”或“补充录屏修订需求”的流程。

### 目标

- [x] 创建需求弹窗中的描述输入框支持直接粘贴图片
- [x] 创建需求弹窗中的描述输入框支持选择视频附件
- [x] Requirement 编辑面板中的摘要输入框支持直接粘贴图片
- [x] Requirement 编辑面板中的摘要输入框支持选择视频附件
- [x] 创建需求弹窗提供显式的图片选择入口
- [x] Requirement 编辑面板提供显式的图片选择入口
- [x] 创建前展示附件预览，并允许移除
- [x] 编辑前展示附件预览，并允许移除
- [x] 创建和编辑成功后，需求文本与视觉附件作为同一条上下文日志写入任务历史
- [x] 保持 `requirement_brief` 在文字为空时也可回退为可用摘要，避免图片/视频型需求直接卡在校验上
- [x] 常见 BMP 截图 MIME 可通过后端图片上传流程
- [x] 前端以 `FormData` 上传图片/视频时，后端必须正确绑定 `task_id` 与 `text_content`

### 非目标

- 不改动后端任务创建 API 的合同
- 不把 Requirement 创建/编辑面板扩展成任意文件上传中心
- 不引入新的任务创建或需求更新后端接口

## 2. Implementation Guide

### 核心逻辑

1. 在 `frontend/src/App.tsx` 为创建需求弹窗和 Requirement 编辑面板新增独立的 `AttachmentDraft` 状态与隐藏文件输入。
2. 为两个 textarea 增加 `onPaste` 处理器，优先从 `clipboardData.items` 读取文件，回退到 `clipboardData.files`，并补齐缺失的文件名/MIME。
3. 在两个面板中复用现有附件预览卡片样式，展示图片/视频名称、大小和移除按钮。
4. 创建任务时仍先调用 `taskApi.create(...)`；编辑需求时仍先调用 `taskApi.update(...)`。
5. 若用户附带图片，则使用 `mediaApi.uploadImage(...)` 把需求文字与图片作为同一条日志写入；若用户附带视频，则使用 `mediaApi.uploadAttachment(...)` 写入同一条带附件日志。
6. 当用户只提供图片或视频时，前端会为 `requirement_brief` 生成可用的回退摘要，避免需求在创建/编辑阶段被空文本校验卡住。
7. 后端 `MediaService` 额外接受 BMP 和常见 legacy image MIME，兼容截图工具的输出；视频继续走通用附件存储路径。
8. `dsl/api/media.py` 的上传路由必须用 FastAPI `File(...)` / `Form()` 显式声明 multipart 字段，确保 create/edit Requirement 上传时不会丢失 `task_id`。

### Change Matrix

| Change Target | Current State | Target State | Delivered Change |
|---|---|---|---|
| 创建需求弹窗描述框 | 仅支持纯文本 | 支持粘贴图片/视频与文件选择图片/视频 | 在 `frontend/src/App.tsx` 中新增 create-modal 附件状态、粘贴处理和隐藏文件输入 |
| Requirement 编辑摘要框 | 仅支持纯文本 | 支持粘贴图片/视频与文件选择图片/视频 | 在 `frontend/src/App.tsx` 中为 edit panel 新增同等附件状态、粘贴处理和隐藏文件输入 |
| 创建/编辑前附件反馈 | 无预览、无法移除 | 可预览已选图片/视频并移除 | 复用现有附件卡片 UI，在创建与编辑面板内展示草稿附件 |
| 需求日志写入 | 始终创建纯文本 DevLog | 有图片/视频时创建“文本 + 附件”的合并日志 | 在 `handleCreateRequirement()` 和 `handleSaveRequirementChanges()` 中切换为媒体/附件上传路径 |
| 媒体上传 API 绑定 | `task_id` / `text_content` 在 multipart 请求中可能丢失 | 上传日志必须始终落到当前 Requirement | 在 `dsl/api/media.py` 中为上传参数补上 `File(...)` / `Form()` |
| 图片兼容性 | 仅接受少量标准 MIME | 接受常见 BMP/legacy image MIME | 在 `dsl/services/media_service.py` 中扩展允许的图片 MIME 集合 |
| 样式 | 无 Requirement create/edit 附件入口样式 | 附件按钮与提示文案纳入两个面板 | 在 `frontend/src/index.css` 中复用 create-panel attach/composer 样式 |

## 3. Functional Requirements

1. 创建需求弹窗中的描述 textarea 必须支持粘贴图片。
2. Requirement 编辑面板中的摘要 textarea 也必须支持粘贴图片。
3. 创建和编辑面板都必须提供显式的图片/视频选择按钮，且文件选择器覆盖 `image/*,video/*`。
4. 用户选择或粘贴视觉附件后，界面必须显示附件预览与文件元信息。
5. 用户在提交前必须可以移除已选图片或视频。
6. 创建或编辑 Requirement 时，若存在图片/视频附件，系统必须把文字与附件合并写入同一条需求日志，避免重复创建两条描述日志。
7. 当用户只提供图片或视频时，前端仍必须生成可用的 `requirement_brief`，避免因空文字而阻断创建/编辑。
8. 常见 BMP 和 legacy 截图 MIME 必须通过图片上传流程。
9. 前端通过 multipart `FormData` 提交图片或视频时，后端必须把 `task_id` 和 `text_content` 绑定到同一条日志创建请求。
10. 现有已创建任务的反馈附件流程不能被这次改动回归。

## 4. Verification

- [x] `npm --prefix frontend run build`
- [x] `uv run pytest tests/test_media_api.py tests/test_media_service.py -q`
- [x] `just docs-build`
- [x] `curl -s -X POST http://127.0.0.1:8000/api/media/upload-attachment ...`

## 5. Delivered Outcome

### 已交付内容

- `frontend/src/App.tsx`
  - 新增 create/edit Requirement 面板专用附件状态、剪贴板文件处理、图片/视频选择器、预览和移除逻辑
  - 复用已有附件草稿构造逻辑，避免反馈输入框与创建弹窗走出两套不一致实现
  - 调整创建和编辑流程：图片走媒体接口、视频走附件接口，统一写入“描述/修订 + 附件”的组合日志
  - 允许视觉型需求在无文字时通过回退摘要继续提交
- `dsl/api/media.py`
  - 为 `/api/media/upload` 和 `/api/media/upload-attachment` 显式声明 `File(...)` / `Form()` 参数，修复 multipart 上传时 `task_id` 与 `text_content` 丢失的问题
- `frontend/src/index.css`
  - 新增 Requirement create/edit 面板 attach 按钮、视频预览兼容和提示文案样式
- `dsl/services/media_service.py`
  - 扩展允许的图片 MIME，覆盖 BMP 和常见 legacy alias
- `tests/test_media_api.py`
  - 新增媒体上传路由回归测试，验证 multipart `task_id` / `text_content` 能正确绑定到目标 Requirement
- `tests/test_media_service.py`
  - 新增 BMP 上传回归测试

### 实际验证结果

- `npm --prefix frontend run build` 通过
- `uv run pytest tests/test_media_api.py tests/test_media_service.py -q` 通过（`3 passed in 1.01s`）
- `just docs-build` 通过
- 真实文件 `/home/atahang/codes/koda/PixPin_2026-03-25_11-40-59.mp4` 手工上传验证通过：新建任务 `f791dacc-c769-46cc-ae32-f1b5397f068d` 后，上传响应日志 `06b37d2c-1e7a-4315-9f98-07b692185094` 返回同一个 `task_id`

### 风险与后续项

- 本次未在终端内做浏览器级拖拽/粘贴手工交互验证，当前验证以 TypeScript/Vite 编译、后端回归测试和真实 mp4 API 上传为主。
- 当前前端已允许纯图片/视频 Requirement，但任务列表中的摘要在无文字时会回退为自动生成的占位摘要，而不是语义化自然语言描述。
