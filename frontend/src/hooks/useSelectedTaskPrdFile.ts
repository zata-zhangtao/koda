/** Selected-task PRD polling hook
 *
 * Tracks the persisted PRD file for the current task and fail-closes
 * `prd_waiting_confirmation` until the current PRD cycle has fetched a real file.
 */

import { useEffect, useMemo, useState } from "react";
import type { WorkflowStage } from "../types";

export interface SelectedTaskPrdFileSnapshot {
  content: string | null;
  path: string | null;
}

interface ResolvedSelectedTaskPrdFileSnapshot extends SelectedTaskPrdFileSnapshot {
  taskId: string | null;
}

export interface UseSelectedTaskPrdFileParams {
  detailTaskId: string | null;
  selectedTaskStage: WorkflowStage | null;
  selectedTaskStageUpdatedAt: string | null;
  selectedTaskWorktreePath: string | null;
  getPrdFile: (
    taskId: string
  ) => Promise<SelectedTaskPrdFileSnapshot>;
  pollIntervalMs?: number;
}

export interface UseSelectedTaskPrdFileResult extends SelectedTaskPrdFileSnapshot {
  resolvedTaskId: string | null;
  currentWaitingConfirmationLoadCycleKey: string | null;
  hasLoadedCurrentWaitingConfirmationPrdFile: boolean;
  isCurrentWaitingConfirmationPrdFileInitialLoadPending: boolean;
}

const PRD_WAITING_CONFIRMATION_STAGE_VALUE = "prd_waiting_confirmation";
const PRD_RELEVANT_STAGE_VALUE_SET = new Set<string>([
  PRD_WAITING_CONFIRMATION_STAGE_VALUE,
  "implementation_in_progress",
  "self_review_in_progress",
  "test_in_progress",
  "pr_preparing",
  "acceptance_in_progress",
  "changes_requested",
]);

function arePrdFileSnapshotsEqual(
  previousPrdFileSnapshot: ResolvedSelectedTaskPrdFileSnapshot,
  nextPrdFileSnapshot: ResolvedSelectedTaskPrdFileSnapshot
): boolean {
  return (
    previousPrdFileSnapshot.taskId === nextPrdFileSnapshot.taskId &&
    previousPrdFileSnapshot.content === nextPrdFileSnapshot.content &&
    previousPrdFileSnapshot.path === nextPrdFileSnapshot.path
  );
}

export function buildWaitingConfirmationPrdLoadCycleKey({
  detailTaskId,
  selectedTaskStage,
  selectedTaskStageUpdatedAt,
  selectedTaskWorktreePath,
}: Pick<
  UseSelectedTaskPrdFileParams,
  | "detailTaskId"
  | "selectedTaskStage"
  | "selectedTaskStageUpdatedAt"
  | "selectedTaskWorktreePath"
>): string | null {
  if (
    !detailTaskId ||
    !selectedTaskStageUpdatedAt ||
    selectedTaskWorktreePath === null ||
    selectedTaskStage !== PRD_WAITING_CONFIRMATION_STAGE_VALUE
  ) {
    return null;
  }

  return `${detailTaskId}:${selectedTaskStageUpdatedAt}`;
}

export function useSelectedTaskPrdFile({
  detailTaskId,
  selectedTaskStage,
  selectedTaskStageUpdatedAt,
  selectedTaskWorktreePath,
  getPrdFile,
  pollIntervalMs = 2000,
}: UseSelectedTaskPrdFileParams): UseSelectedTaskPrdFileResult {
  const [selectedTaskPrdFileSnapshot, setSelectedTaskPrdFileSnapshot] =
    useState<ResolvedSelectedTaskPrdFileSnapshot>({
      taskId: null,
      content: null,
      path: null,
    });
  const [
    lastLoadedWaitingConfirmationCycleKey,
    setLastLoadedWaitingConfirmationCycleKey,
  ] = useState<string | null>(null);

  const currentWaitingConfirmationLoadCycleKey = useMemo(
    () =>
      buildWaitingConfirmationPrdLoadCycleKey({
        detailTaskId,
        selectedTaskStage,
        selectedTaskStageUpdatedAt,
        selectedTaskWorktreePath,
      }),
    [
      detailTaskId,
      selectedTaskStage,
      selectedTaskStageUpdatedAt,
      selectedTaskWorktreePath,
    ]
  );
  const isPrdPollingActive =
    detailTaskId !== null &&
    selectedTaskWorktreePath !== null &&
    selectedTaskStage !== null &&
    PRD_RELEVANT_STAGE_VALUE_SET.has(selectedTaskStage);

  useEffect(() => {
    setSelectedTaskPrdFileSnapshot({
      taskId: null,
      content: null,
      path: null,
    });
    setLastLoadedWaitingConfirmationCycleKey(null);
  }, [detailTaskId]);

  useEffect(() => {
    if (!detailTaskId || !isPrdPollingActive) {
      return;
    }

    let isCancelled = false;

    const loadSelectedTaskPrdFile = async () => {
      try {
        const fetchedSelectedTaskPrdFileSnapshot = await getPrdFile(detailTaskId);
        if (isCancelled) {
          return;
        }

        const nextSelectedTaskPrdFileSnapshot = {
          taskId: detailTaskId,
          ...fetchedSelectedTaskPrdFileSnapshot,
        };
        setSelectedTaskPrdFileSnapshot((previousPrdFileSnapshot) =>
          arePrdFileSnapshotsEqual(
            previousPrdFileSnapshot,
            nextSelectedTaskPrdFileSnapshot
          )
            ? previousPrdFileSnapshot
            : nextSelectedTaskPrdFileSnapshot
        );
        if (
          currentWaitingConfirmationLoadCycleKey !== null &&
          nextSelectedTaskPrdFileSnapshot.path !== null
        ) {
          setLastLoadedWaitingConfirmationCycleKey(
            currentWaitingConfirmationLoadCycleKey
          );
        }
      } catch {
        // Ignore transient polling failures and let the next interval retry.
      }
    };

    void loadSelectedTaskPrdFile();
    const prdPollId = globalThis.setInterval(() => {
      void loadSelectedTaskPrdFile();
    }, pollIntervalMs);

    return () => {
      isCancelled = true;
      globalThis.clearInterval(prdPollId);
    };
  }, [
    currentWaitingConfirmationLoadCycleKey,
    detailTaskId,
    getPrdFile,
    isPrdPollingActive,
    pollIntervalMs,
  ]);

  const hasLoadedCurrentWaitingConfirmationPrdFile =
    currentWaitingConfirmationLoadCycleKey !== null &&
    lastLoadedWaitingConfirmationCycleKey ===
      currentWaitingConfirmationLoadCycleKey &&
    selectedTaskPrdFileSnapshot.path !== null;
  const isCurrentWaitingConfirmationPrdFileInitialLoadPending =
    currentWaitingConfirmationLoadCycleKey !== null &&
    !hasLoadedCurrentWaitingConfirmationPrdFile;

  return {
    content: selectedTaskPrdFileSnapshot.content,
    path: selectedTaskPrdFileSnapshot.path,
    resolvedTaskId: selectedTaskPrdFileSnapshot.taskId,
    currentWaitingConfirmationLoadCycleKey,
    hasLoadedCurrentWaitingConfirmationPrdFile,
    isCurrentWaitingConfirmationPrdFileInitialLoadPending,
  };
}
