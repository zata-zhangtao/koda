# Findings & Decisions

## Requirements
- Rewrite the existing `frontend/` implementation based on `/Users/zata/code/koda/ai-devflow.zip`.
- Aim for pixel-level reproduction of the reference app's UI, which means matching layout, spacing, visual hierarchy, typography, colors, and interaction structure rather than preserving the current frontend's visual design.
- Deliver the rewrite inside the current repo's `frontend/` app.

## Research Findings
- The current project already contains a standalone Vite app in `frontend/`.
- The current app is a three-column developer-log interface with custom sidebar, stream, and input components.
- `ai-devflow.zip` contains a separate React/Vite frontend with its own `src/App.tsx`, `src/components/UI.tsx`, `src/index.css`, `vite.config.ts`, `package.json`, and supporting service/type files.
- Because the reference is a codebase rather than a static mockup, the most reliable way to achieve parity is to inspect and port its component tree and styling system directly.
- The reference app uses a warm off-white canvas, black/stone typography, rounded white cards, a sticky translucent header, a fixed black footer, and a two-column dashboard layout with a requirement list on the left and a detail view on the right.
- The reference app's interaction model is: create requirement -> select requirement -> view timeline and PRD -> start task / confirm PRD -> send feedback.
- The reference app depends on `firebase`, `@google/genai`, `motion`, `lucide-react`, `clsx`, `tailwind-merge`, Tailwind CSS v4, and React 19.
- The current app depends only on React 18, React Markdown, and Vite; it fetches data from `/api` endpoints for run accounts, tasks, logs, media, and chronicle data.
- The current backend shape does not match the reference app's Firebase requirement/history collections, so the UI must adapt current task/log data into the reference screens instead of copying the data layer directly.
- The repository does not contain `mkdocs.yml` or a `docs/` tree, so there was no project documentation build to run for this frontend-only change.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Perform a structure-first migration | Matching the reference layout requires replacing the root component tree before fine-tuning styling details. |
| Use the existing `frontend/` app as the target shell for the rewrite | This keeps the deliverable aligned with the current repository layout and existing scripts. |
| Avoid a direct dependency migration to the reference package manifest | Installing or reconciling the reference dependency stack is unnecessary for UI parity and would introduce Firebase/Gemini-specific runtime requirements into this repo. |
| Rebuild the reference visuals with plain React + CSS modules/global CSS style patterns already available in the repo | This keeps the result buildable in the current environment while still allowing close visual reproduction. |
| Represent selected task logs as the reference-style timeline and derive PRD/detail content from available task/log fields | This preserves working data flow even though the current backend does not expose a true PRD document model. |
| Leave the legacy component files in place but clean their strict-TypeScript issues | The new `App.tsx` no longer imports them, but they still participate in compilation because the project type-checks the entire `src/` tree. |

## Issues Encountered
| Issue | Resolution |
|-------|------------|

## Resources
- `/Users/zata/code/koda/ai-devflow.zip`
- `/Users/zata/code/koda/frontend/package.json`
- `/Users/zata/code/koda/frontend/src/App.tsx`
- `/tmp/koda-ai-devflow/src/App.tsx`
- `/tmp/koda-ai-devflow/src/components/UI.tsx`
- `/tmp/koda-ai-devflow/src/index.css`

## Follow-up Findings (2026-03-17)
- The current right-side feedback composer in `frontend/src/App.tsx` scrolls away with the page because the detail column is not a fixed-height pane with an internal scroll region.
- The old unused `frontend/src/components/InputBox.tsx` already contains working pasted-image detection logic that can be adapted into the new dashboard composer.
- The backend currently supports image uploads only via `/api/media/upload`; there is no generic file upload endpoint, and the existing log schema only has image path fields.
- The SQLite `tasks` table stores `lifecycle_status` as a plain `VARCHAR(7)` without a check constraint, so extending the task status enum does not require a schema migration for the existing local database.
- The current task API lacks requirement edit/delete endpoints; it only supports create, fetch, and status updates.
- Requirement descriptions are currently derived from the first text log, so a requirement update must either change that derivation logic or append structured history entries that the UI can parse as the latest requirement snapshot.
- Modified requirements should preserve earlier execution history and append changes as new timeline entries instead of overwriting prior content.

## Follow-up Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Add a dedicated archive-style split between active, completed, and changed requirements | This satisfies the request for a separate completed-task interface while still surfacing deleted/modified requirements cleanly. |
| Represent requirement edits/deletions as structured markdown logs with hidden markers | The UI can derive the latest requirement snapshot and change history without altering the `dev_logs` schema. |
| Add a generic attachment upload API that stores files under the existing media root and injects a markdown link into the new log entry | This enables pasted files with minimal backend surface area and keeps timeline rendering compatible with React Markdown. |
