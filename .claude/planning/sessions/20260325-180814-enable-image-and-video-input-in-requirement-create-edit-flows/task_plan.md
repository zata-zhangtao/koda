# Task Plan: Enable Image And Video Input In Requirement Create/Edit Flows

## Goal
Allow the requirement create and edit inputs to accept image and video attachments so users can paste or select visual context while creating or revising a task.

## Current Phase
Phase 4

## Phases

### Phase 1: Discovery
- [x] Trace the create-requirement modal submit flow and existing attachment helpers
- [x] Decide how the initial requirement text and attachment should be persisted without duplicate logs
- [x] Record evidence in `findings.md`
- **Status:** complete
- **Started:** 2026-03-25 10:15:00
- **Completed:** 2026-03-25 10:20:00

### Phase 2: Implementation
- [x] Add create-modal attachment draft state plus paste/file-picker support
- [x] Add the same attachment flow to the requirement editor
- [x] Extend attachment typing and previews to cover video alongside image/file
- [x] Reuse the existing media upload API after task creation/update
- [x] Keep the stored `requirement_brief` behavior coherent for task summaries, including image/video-only submissions
- [x] Fix backend multipart form binding so upload `task_id` and `text_content` survive `FormData` requests
- [x] Add targeted API regression coverage for the media upload routes
- **Status:** complete
- **Started:** 2026-03-25 10:20:00
- **Completed:** 2026-03-25 11:47:00

### Phase 3: Verification
- [x] Run the relevant frontend verification command
- [x] Run targeted backend verification for image MIME compatibility and multipart task binding
- [x] Run a real mp4 upload against the local server and confirm the attachment stays on the intended task
- [x] Record exact commands and outcomes in `progress.md`
- **Status:** complete
- **Started:** 2026-03-25 11:18:00
- **Completed:** 2026-03-25 11:56:00

### Phase 4: Delivery
- [x] Update or create the matching PRD in `tasks/`
- [x] Summarize the fix, verification, and residual risks
- **Status:** complete
- **Started:** 2026-03-25 11:28:00
- **Completed:** 2026-03-25 11:57:00

## Key Questions
1. Which input box is the user referring to, and is it the same composer that already supports attachments?
2. Should the create flow create one combined initial log when an attachment exists, or separate text and attachment logs?
3. Can the feature be delivered as a frontend-only change by uploading the attachment after the task record exists?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Repoint the active planning workspace to this new task | The previous notes were for an unrelated resume bug |
| Reuse the existing media upload APIs instead of adding a new task-creation endpoint | The backend already supports task-scoped attachment logs once the task exists |
| Store one combined initial log when an attachment exists | This preserves the requirement text and image together without duplicating the description in a second log |
| Extend the requirement editor to use the same attachment contract as create | Users need consistent image support before and after task creation |
| Allow image-only requirement submission/edit by synthesizing a fallback `requirement_brief` | This removes the remaining blocker where pasting an image alone still failed validation |
| Accept common BMP and legacy image MIME aliases on the backend | Clipboard screenshots can arrive as `image/bmp` or similar aliases and should not be rejected |
| Route videos through the generic attachment API while keeping inline preview in the UI | Videos do not belong on the image-specific pipeline, but users still need visible confirmation before submit |
| Annotate the media upload route parameters with FastAPI `File`/`Form` | Frontend uploads use `FormData`, so plain function parameters were dropping `task_id` and `text_content` |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Active planning session contained stale notes from a previous task | 1 | Replaced the planning files with notes for the create-modal image-input bug |
| Requirement video uploads were landing on the wrong task | 1 | Verified the media API was not binding multipart `task_id`/`text_content`, then patched the route signatures and added regression tests |

## Completion Summary

- **Status:** Complete (2026-03-25)
- **Tests:** Passed (`npm --prefix frontend run build`, `uv run pytest tests/test_media_api.py tests/test_media_service.py -q`, `just docs-build`, manual `curl` upload of `/home/atahang/codes/koda/PixPin_2026-03-25_11-40-59.mp4`)
- **PRD:** Updated `tasks/20260325-105411-prd-create-requirement-image-input.md`
- **Deliverables:** `frontend/src/App.tsx`, `frontend/src/index.css`, `dsl/api/media.py`, `dsl/services/media_service.py`, `tests/test_media_api.py`, `tests/test_media_service.py`
- **Notes:** The final blocker was not video size; the backend media routes were dropping multipart `task_id`/`text_content`, so uploads could attach to the wrong requirement until the `File`/`Form` fix landed
