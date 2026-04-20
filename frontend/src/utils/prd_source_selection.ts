/** PRD source selection utilities. */

export type PrdSourceMode = "ai_generate" | "pending" | "manual_import";
export type ManualImportEntryMode = "upload" | "paste";

export const PRD_SOURCE_MODE_LABEL_MAP: Record<PrdSourceMode, string> = {
  ai_generate: "AI 生成 PRD",
  pending: "从 tasks/pending 选择",
  manual_import: "手动导入 PRD",
};

export const MANUAL_IMPORT_ENTRY_MODE_LABEL_MAP: Record<
  ManualImportEntryMode,
  string
> = {
  upload: "上传文件",
  paste: "粘贴内容",
};

export function canSubmitPrdSourceAction(
  prdSourceMode: PrdSourceMode,
  selectedPendingPrdRelativePath: string | null,
  manualImportPrdFile: File | null,
  manualImportEntryMode: ManualImportEntryMode,
  manualImportPrdMarkdownText: string
): boolean {
  if (prdSourceMode === "ai_generate") {
    return true;
  }
  if (prdSourceMode === "pending") {
    return Boolean(selectedPendingPrdRelativePath);
  }
  if (manualImportEntryMode === "paste") {
    return manualImportPrdMarkdownText.trim().length > 0;
  }
  return manualImportPrdFile !== null;
}

export function isMarkdownPrdImportFile(candidateFile: File): boolean {
  const normalizedFileName = candidateFile.name.trim().toLowerCase();
  const normalizedFileType = candidateFile.type.trim().toLowerCase();
  return (
    normalizedFileName.endsWith(".md") ||
    normalizedFileType === "text/markdown" ||
    normalizedFileType === "text/x-markdown"
  );
}

export function getPrdSourceActionLabel(prdSourceMode: PrdSourceMode): string {
  if (prdSourceMode === "pending") {
    return "使用选中的 PRD";
  }
  if (prdSourceMode === "manual_import") {
    return "导入 PRD";
  }
  return "开始任务";
}
