const ARCHIVED_TASK_PRD_PATH_MARKER_LIST = ["/tasks/archive/", "\\tasks\\archive\\"];

export function isArchivedTaskPrdFilePath(
  prdFilePathText: string | null
): boolean {
  if (!prdFilePathText) {
    return false;
  }

  return ARCHIVED_TASK_PRD_PATH_MARKER_LIST.some((pathMarkerText) =>
    prdFilePathText.includes(pathMarkerText)
  );
}

export function buildArchivedTaskPrdNoticeText(
  prdFilePathText: string | null
): string | null {
  if (!isArchivedTaskPrdFilePath(prdFilePathText)) {
    return null;
  }

  return "当前展示的是 tasks/archive/ 中的已归档 PRD。它仍然对应当前任务的同一份 PRD 文档，但 live tasks 根目录里已经没有可读的活动 PRD 文件。";
}
