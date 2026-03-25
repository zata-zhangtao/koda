# Findings & Decisions

## Requirements
- The highlighted textarea in the create-requirement modal should accept visual attachments, not just plain text.
- The same image/video capability is also needed when editing an existing Requirement.

## Research Findings
- `frontend/src/App.tsx` uses a separate create-modal flow in `handleCreateRequirement()`.
- `frontend/src/App.tsx` also uses a separate requirement editor flow in `handleSaveRequirementChanges()`.
- The create modal currently only stores `newRequirementTitle`, `newRequirementDescription`, and `newRequirementProjectId`; it has no attachment draft state, no paste handler, and no file input.
- The requirement editor likewise started as text-only and only wrote a plain requirement-update log entry.
- The existing feedback composer already supports `AttachmentDraft`, paste handling, preview rendering, and upload via `mediaApi.uploadImage(...)` / `mediaApi.uploadAttachment(...)`.
- `handleCreateRequirement()` currently creates the task, then writes a plain-text DevLog with the same description.
- When an attachment exists, the cleanest non-duplicating flow is: create the task with `requirement_brief`, then upload the attachment with the description as the upload text so the initial log is combined instead of duplicated.
- Backend media routes already accept a `task_id` and create task-scoped logs, so no new backend API is required for this feature.
- The media routes originally declared `UploadFile`, `text_content`, and `task_id` as plain parameters, but the frontend sends `FormData`; without `File(...)` / `Form()`, FastAPI was not binding `task_id` and `text_content` from multipart uploads.
- The final implementation reused the feedback composer’s attachment preview visuals, but kept a dedicated create-modal attach control and textarea paste handler.
- The create and edit file pickers now need to cover both `image/*` and `video/*`, while pasted clipboard files still flow through the shared attachment draft helper.
- Some clipboard providers expose images via `clipboardData.files` or legacy MIME aliases like `image/bmp`, so frontend file normalization and backend MIME acceptance both matter.
- Videos can stay on the generic attachment route because downstream task context extraction already resolves attachment markdown back to local file paths.
- A real `curl` upload of `/home/atahang/codes/koda/PixPin_2026-03-25_11-40-59.mp4` reproduced the bug before the backend fix by returning a different `task_id` than the one submitted.
- The reported mp4 is only 604,380 bytes, well under the 10 MB attachment limit, so file size was not the cause of the failed upload.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Implement the feature in the frontend create/edit flows | Existing backend upload APIs already cover the storage contract |
| Reuse the existing attachment-preview and upload patterns from the feedback composer | Keeps behavior consistent and reduces new surface area |
| Keep `requirement_brief` populated even for image-only submissions | The requirement list and downstream task summary logic depend on it |
| Accept BMP and legacy image MIME aliases in `MediaService` | This makes screenshot paste/upload paths more robust on Windows and some clipboard tools |
| Treat videos as first-class UI attachments but persist them through `uploadAttachment(...)` | This keeps backend media semantics simple while still supporting requirement videos |
| Fix multipart binding in `dsl/api/media.py` instead of changing the frontend payload shape | The frontend was already correctly sending `FormData`; the bug lived in FastAPI parameter declarations |
| Add regression tests for both `/api/media/upload` and `/api/media/upload-attachment` | The failure mode is subtle and easy to reintroduce when the route signatures change |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| The user originally referenced a video without a precise control name | The follow-up screenshot clarified that the target is the create-requirement description textarea |
| Frontend create/edit support alone did not fix “视频发不过去” | Direct API verification exposed a backend multipart binding bug that had to be fixed separately |

## Resources
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/src/api/client.ts`
- `dsl/api/media.py`
- `dsl/services/media_service.py`
- `tests/test_media_api.py`
- `tests/test_media_service.py`
- `tasks/20260325-105411-prd-create-requirement-image-input.md`
