# Findings & Decisions
<!--
  WHAT: Your knowledge base for the task. Stores everything you discover and decide.
  WHY: Context windows are limited. This file is your "external memory" - persistent and unlimited.
  WHEN: Update after ANY discovery, especially after 2 view/browser/search operations (2-Action Rule).
-->

## Requirements
<!--
  WHAT: What the user asked for, broken down into specific requirements.
  WHY: Keeps requirements visible so you don't forget what you're building.
  WHEN: Fill this in during Phase 1 (Requirements & Discovery).
  EXAMPLE:
    - Command-line interface
    - Add tasks
    - List all tasks
    - Delete tasks
    - Python implementation
-->
<!-- Captured from user request -->
- Restore the task-sidecar Q&A panel for `DELETED` tasks without reopening write access.
- Keep archived sidecar Q&A history readable and preserve the “整理最近一次结论为反馈草稿” entry.
- Avoid expanding scope beyond the deleted-task visibility regression already implied by the active PRD/docs.

## Research Findings
<!--
  WHAT: Key discoveries from web searches, documentation reading, or exploration.
  WHY: Multimodal content (images, browser results) doesn't persist. Write it down immediately.
  WHEN: After EVERY 2 view/browser/search operations, update this section (2-Action Rule).
  EXAMPLE:
    - Python's argparse module supports subcommands for clean CLI design
    - JSON module handles file persistence easily
    - Standard pattern: python script.py <command> [args]
-->
<!-- Key discoveries during exploration -->
- `frontend/src/App.tsx` currently computes `canRenderComposer` as false for `DELETED`, which hides the entire feedback / sidecar area for deleted tasks even though the sidecar branch already has read-only copy for archived tasks.
- `frontend/src/App.tsx` separately computes `canSendTaskQa` and `canSendFeedback` as false for archived tasks, so the UI already has the correct read-only behavior once the panel is rendered.
- `tasks/prd-514e2c11.md` records a delivered review-fix stating that completed tasks should still show historical sidecar Q&A and keep the “整理最近一次结论为反馈草稿” action available while blocking new questions and formal feedback.
- `docs/architecture/system-design.md` and `docs/dev/evaluation.md` both explicitly say archived tasks should retain readable sidecar Q&A history plus the feedback-draft conversion entry.
- Existing backend routes already support archived history reads: `dsl/api/task_qa.py:list_task_qa_messages()` only checks task accessibility, while writes remain blocked by `TaskQaService.create_question()`.
- The only remaining working-tree change for this review-fix is `frontend/src/App.tsx`, where `canRenderComposer` now uses `selectedTask !== null` so deleted tasks still render the read-only sidecar/feedback panel.
- Focused verification now passes for the affected scope: `uv run pytest tests/test_task_qa_api.py -q`, `uv run pytest tests/test_task_qa_api.py tests/test_tasks_api.py tests/test_logs_api.py tests/test_media_api.py -q`, `cd frontend && npm run build`, and `just docs-build`.

## Technical Decisions
<!--
  WHAT: Architecture and implementation choices you've made, with reasoning.
  WHY: You'll forget why you chose a technology or approach. This table preserves that knowledge.
  WHEN: Update whenever you make a significant technical choice.
  EXAMPLE:
    | Use JSON for storage | Simple, human-readable, built-in Python support |
    | argparse with subcommands | Clean CLI: python todo.py add "task" |
-->
<!-- Decisions made with rationale -->
| Decision | Rationale |
|----------|-----------|
| Fix the regression in `frontend/src/App.tsx` instead of changing service-layer behavior | Backend read semantics and docs already agree that archived sidecar history should stay visible |
| Add a focused API/service regression test for deleted-task message listing | The bug surfaced in UI, but a backend read test locks in the documented archived-history contract |

## Issues Encountered
<!--
  WHAT: Problems you ran into and how you solved them.
  WHY: Similar to errors in task_plan.md, but focused on broader issues (not just code errors).
  WHEN: Document when you encounter blockers or unexpected challenges.
  EXAMPLE:
    | Empty file causes JSONDecodeError | Added explicit empty file check before json.load() |
-->
<!-- Errors and how they were resolved -->
| Issue | Resolution |
|-------|------------|
| Active planning session described the same deleted-task visibility bug but findings/progress were empty | Reused the active plan and wrote the concrete root cause plus supporting doc evidence before editing code |

## Resources
<!--
  WHAT: URLs, file paths, API references, documentation links you've found useful.
  WHY: Easy reference for later. Don't lose important links in context.
  WHEN: Add as you discover useful resources.
  EXAMPLE:
    - Python argparse docs: https://docs.python.org/3/library/argparse.html
    - Project structure: src/main.py, src/utils.py
-->
<!-- URLs, file paths, API references -->
- `frontend/src/App.tsx`
- `tasks/prd-514e2c11.md`
- `docs/architecture/system-design.md`
- `docs/dev/evaluation.md`
- `dsl/api/task_qa.py`
- `dsl/services/task_qa_service.py`

## Visual/Browser Findings
<!--
  WHAT: Information you learned from viewing images, PDFs, or browser results.
  WHY: CRITICAL - Visual/multimodal content doesn't persist in context. Must be captured as text.
  WHEN: IMMEDIATELY after viewing images or browser results. Don't wait!
  EXAMPLE:
    - Screenshot shows login form has email and password fields
    - Browser shows API returns JSON with "status" and "data" keys
-->
<!-- CRITICAL: Update after every 2 view/browser operations -->
<!-- Multimodal content must be captured as text immediately -->
-

---
<!--
  REMINDER: The 2-Action Rule
  After every 2 view/browser/search operations, you MUST update this file.
  This prevents visual information from being lost when context resets.
-->
*Update this file after every 2 view/browser/search operations*
*This prevents visual information from being lost*
