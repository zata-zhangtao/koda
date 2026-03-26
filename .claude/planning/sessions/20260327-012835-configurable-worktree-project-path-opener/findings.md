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
- Replace the hard-coded `trae-cn` launcher used for task worktrees and project roots with a configurable command template.
- Add neutral `POST /api/tasks/{task_id}/open-in-editor` and `POST /api/projects/{project_id}/open-in-editor` endpoints.
- Keep `open-in-trae` routes working as compatibility aliases during the migration window.
- Update the frontend client and UI copy to use neutral editor semantics instead of Trae-specific naming.
- Add automated coverage for template rendering, command errors, new routes, and compatibility behavior.
- Update operator docs and API reference, and keep the existing PRD `tasks/prd-e84b5309.md` synchronized before delivery.

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
- `dsl/api/tasks.py` and `dsl/api/projects.py` currently call `subprocess.Popen(["trae-cn", ...])` directly and each raise their own `FileNotFoundError`-to-HTTP 500 mapping.
- `dsl/services/terminal_launcher.py` already establishes the preferred pattern for a command-template helper: build a template context, render with `str.format`, split with `shlex.split`, and translate placeholder/template problems into a dedicated runtime error type.
- The frontend uses `taskApi.openInTrae` and `projectApi.openInTrae`; `frontend/src/App.tsx` also stores the mutation state key as `"open_trae"` and shows Trae-specific success/error copy.
- `tests/test_terminal_launcher.py` demonstrates the repo's preferred style for focused utility tests around template parsing and platform fallback behavior.
- `tests/test_tasks_api.py` exercises route helper functions directly against an in-memory SQLite session; there is no existing `projects` API test file yet, so adding one is likely the cleanest route-level coverage for the project opener endpoints.
- `docs/getting-started.md` still documents `trae-cn` as an optional tool, while `docs/api/references.md` still exports `open_task_in_trae` and `open_project_in_trae` as the public API members.
- The local shell environment exports SOCKS proxy variables, which causes unrelated full-suite `httpx` tests to require `socksio`; repository verification is stable when those proxy env vars are unset for the test command.

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
| Reuse the terminal launcher's template semantics (`str.format` + `shlex.split`) for path opening | Keeps command-template behavior consistent across local launcher features and minimizes new parsing rules |
| Support placeholders `{target_path}`, `{target_path_shell}`, and `{target_kind}` | Matches the PRD contract and covers raw path, shell-safe path, and caller context without introducing a broader DSL |
| Return route-level 422 for missing target paths but 500 for template/executable errors | Preserves current API semantics: bad task/project state is user-fixable input, while invalid launcher config or missing binaries are server/runtime issues |

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
| Active planning workspace initially contained unrelated migrated sessions | Archived and replaced it with a fresh planning session before continuing |
| Full `pytest` initially failed in unrelated tunnel-agent tests because local SOCKS proxy env polluted `httpx` | Re-ran the full suite with proxy environment variables unset and recorded the caveat in planning + PRD |

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
- `tasks/prd-e84b5309.md`
- `dsl/api/tasks.py`
- `dsl/api/projects.py`
- `dsl/services/terminal_launcher.py`
- `frontend/src/api/client.ts`
- `frontend/src/App.tsx`
- `tests/test_terminal_launcher.py`
- `tests/test_tasks_api.py`
- `tests/test_projects_api.py`
- `tests/test_path_opener.py`
- `docs/getting-started.md`
- `docs/api/references.md`
- `docs/guides/configuration.md`
- `tasks/prd-e84b5309.md`

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
- No browser or image findings in this task.

---
<!--
  REMINDER: The 2-Action Rule
  After every 2 view/browser/search operations, you MUST update this file.
  This prevents visual information from being lost when context resets.
-->
*Update this file after every 2 view/browser/search operations*
*This prevents visual information from being lost*
