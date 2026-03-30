import type { Project } from "../types";

export const ALL_TASK_PROJECT_FILTER_VALUE = "__all__";
export const UNLINKED_TASK_PROJECT_FILTER_VALUE = "__unlinked__";
const PROJECT_LABEL_ID_LENGTH = 8;

export interface TaskProjectFilterRequestOptions {
  projectId?: string | null;
  unlinkedOnly?: boolean;
}

export interface TaskProjectFilterOption {
  label: string;
  value: string;
}

export function buildTaskProjectDisplayLabelMap(
  projectList: Project[]
): Record<string, string> {
  const projectDisplayNameCountMap = projectList.reduce<Map<string, number>>(
    (nextProjectDisplayNameCountMap, projectItem) => {
      const normalizedProjectDisplayName = normalizeProjectDisplayName(
        projectItem.display_name
      );
      nextProjectDisplayNameCountMap.set(
        normalizedProjectDisplayName,
        (nextProjectDisplayNameCountMap.get(normalizedProjectDisplayName) ?? 0) + 1
      );
      return nextProjectDisplayNameCountMap;
    },
    new Map<string, number>()
  );

  return Object.fromEntries(
    projectList.map((projectItem) => [
      projectItem.id,
      buildResolvedProjectDisplayLabel(
        projectItem,
        projectDisplayNameCountMap
      ),
    ])
  );
}

export function buildTaskProjectFilterOptionList(
  projectList: Project[]
): TaskProjectFilterOption[] {
  const taskProjectDisplayLabelMap = buildTaskProjectDisplayLabelMap(projectList);
  return [
    {
      value: ALL_TASK_PROJECT_FILTER_VALUE,
      label: "全部项目",
    },
    {
      value: UNLINKED_TASK_PROJECT_FILTER_VALUE,
      label: "未关联项目",
    },
    ...projectList.map((projectItem) => ({
      value: projectItem.id,
      label:
        taskProjectDisplayLabelMap[projectItem.id] ?? projectItem.display_name,
    })),
  ];
}

export function buildTaskProjectFilterRequestOptions(
  selectedTaskProjectFilterValue: string
): TaskProjectFilterRequestOptions {
  if (
    !selectedTaskProjectFilterValue ||
    selectedTaskProjectFilterValue === ALL_TASK_PROJECT_FILTER_VALUE
  ) {
    return {};
  }

  if (selectedTaskProjectFilterValue === UNLINKED_TASK_PROJECT_FILTER_VALUE) {
    return { unlinkedOnly: true };
  }

  return { projectId: selectedTaskProjectFilterValue };
}

export function shouldReloadTaskProjectFilterData(
  lastRequestedTaskProjectFilterValue: string | null,
  selectedTaskProjectFilterValue: string,
  isDashboardLoading: boolean
): boolean {
  if (isDashboardLoading || lastRequestedTaskProjectFilterValue === null) {
    return false;
  }

  return (
    lastRequestedTaskProjectFilterValue !== selectedTaskProjectFilterValue
  );
}

export function createNextTaskProjectRequestToken(
  previousTaskProjectRequestToken: number
): number {
  return previousTaskProjectRequestToken + 1;
}

export function shouldCommitTaskProjectResponse(
  latestStartedTaskProjectRequestToken: number,
  responseTaskProjectRequestToken: number,
  responseTaskProjectFilterValue: string,
  currentSelectedTaskProjectFilterValue: string
): boolean {
  return (
    latestStartedTaskProjectRequestToken === responseTaskProjectRequestToken &&
    responseTaskProjectFilterValue === currentSelectedTaskProjectFilterValue
  );
}

export function shouldCommitTaskProjectMetadataResponse(
  latestStartedTaskProjectRequestToken: number,
  responseTaskProjectRequestToken: number,
  responseTaskProjectFilterValue: string,
  committedTaskProjectFilterValue: string,
  didCommitResponseTaskListState: boolean
): boolean {
  if (
    latestStartedTaskProjectRequestToken !== responseTaskProjectRequestToken
  ) {
    return false;
  }

  if (didCommitResponseTaskListState) {
    return true;
  }

  return responseTaskProjectFilterValue === committedTaskProjectFilterValue;
}

export function normalizeTaskProjectFilterValue(
  selectedTaskProjectFilterValue: string,
  projectList: Project[]
): string {
  if (
    !selectedTaskProjectFilterValue ||
    selectedTaskProjectFilterValue === ALL_TASK_PROJECT_FILTER_VALUE
  ) {
    return ALL_TASK_PROJECT_FILTER_VALUE;
  }

  if (selectedTaskProjectFilterValue === UNLINKED_TASK_PROJECT_FILTER_VALUE) {
    return UNLINKED_TASK_PROJECT_FILTER_VALUE;
  }

  const hasMatchingProject = projectList.some(
    (projectItem) => projectItem.id === selectedTaskProjectFilterValue
  );
  return hasMatchingProject
    ? selectedTaskProjectFilterValue
    : ALL_TASK_PROJECT_FILTER_VALUE;
}

export function deriveCreateRequirementProjectIdFromFilter(
  selectedTaskProjectFilterValue: string
): string | null {
  if (
    !selectedTaskProjectFilterValue ||
    selectedTaskProjectFilterValue === ALL_TASK_PROJECT_FILTER_VALUE ||
    selectedTaskProjectFilterValue === UNLINKED_TASK_PROJECT_FILTER_VALUE
  ) {
    return null;
  }

  return selectedTaskProjectFilterValue;
}

export function getTaskProjectFilterDisplayLabel(
  selectedTaskProjectFilterValue: string,
  projectList: Project[]
): string {
  const taskProjectDisplayLabelMap = buildTaskProjectDisplayLabelMap(projectList);
  if (
    !selectedTaskProjectFilterValue ||
    selectedTaskProjectFilterValue === ALL_TASK_PROJECT_FILTER_VALUE
  ) {
    return "全部项目";
  }

  if (selectedTaskProjectFilterValue === UNLINKED_TASK_PROJECT_FILTER_VALUE) {
    return "未关联项目";
  }

  const matchedProject = projectList.find(
    (projectItem) => projectItem.id === selectedTaskProjectFilterValue
  );
  return matchedProject
    ? taskProjectDisplayLabelMap[matchedProject.id] ?? matchedProject.display_name
    : "未知项目";
}

function buildResolvedProjectDisplayLabel(
  projectItem: Project,
  projectDisplayNameCountMap: Map<string, number>
): string {
  const normalizedProjectDisplayName = normalizeProjectDisplayName(
    projectItem.display_name
  );
  if (
    (projectDisplayNameCountMap.get(normalizedProjectDisplayName) ?? 0) < 2
  ) {
    return normalizedProjectDisplayName;
  }

  // Duplicate display names need a stable discriminator in every task-facing UI.
  const labelDetailPartList: string[] = [];
  const repoBasename = extractRepoBasename(projectItem.repo_path);
  if (
    repoBasename &&
    repoBasename.toLowerCase() !== normalizedProjectDisplayName.toLowerCase()
  ) {
    labelDetailPartList.push(repoBasename);
  }
  labelDetailPartList.push(projectItem.id.slice(0, PROJECT_LABEL_ID_LENGTH));
  return `${normalizedProjectDisplayName} (${labelDetailPartList.join(" / ")})`;
}

function normalizeProjectDisplayName(rawProjectDisplayName: string): string {
  return rawProjectDisplayName.trim() || "未命名项目";
}

function extractRepoBasename(rawRepoPath: string): string | null {
  const normalizedRepoPath = rawRepoPath.trim().replace(/[/\\]+$/g, "");
  if (!normalizedRepoPath) {
    return null;
  }

  const repoPathSegmentList = normalizedRepoPath.split(/[/\\]+/);
  const repoBasename = repoPathSegmentList[repoPathSegmentList.length - 1];
  return repoBasename?.trim() || null;
}
