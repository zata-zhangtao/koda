import { useEffect, useMemo, useState } from "react";

import { chronicleApi, projectApi, taskApi } from "../api/client";
import { formatDateTime } from "../utils/datetime";
import {
  PROJECT_TIMELINE_DEFAULT_STATUS_FILTER_LIST,
  TaskLifecycleStatus,
  type Project,
  type ProjectTimelineEntry,
  type ProjectTimelineSummary,
  type ProjectTimelineTaskDetail,
  type Task,
} from "../types";

const ALL_PROJECTS_OPTION_VALUE = "__ALL_PROJECTS__";
const ALL_PROJECT_CATEGORIES_OPTION_VALUE = "__ALL_PROJECT_CATEGORIES__";
const UNCATEGORIZED_PROJECT_LABEL = "未分类";
const UNASSIGNED_PROJECT_LABEL = "未绑定项目";

type TimelineCategorySection = {
  categoryLabel: string;
  entryList: ProjectTimelineEntry[];
  projectCount: number;
  totalLogs: number;
  bugCount: number;
  fixCount: number;
  lastActivityAt: string | null;
};

function buildDateFilterIsoText(
  rawDateText: string,
  boundary: "start" | "end"
): string | null {
  const normalizedDateText = rawDateText.trim();
  if (!normalizedDateText) {
    return null;
  }
  return boundary === "start"
    ? `${normalizedDateText}T00:00:00`
    : `${normalizedDateText}T23:59:59`;
}

function formatProjectCategoryLabel(projectCategory: string | null): string {
  const normalizedProjectCategory = projectCategory?.trim() ?? "";
  return normalizedProjectCategory || UNCATEGORIZED_PROJECT_LABEL;
}

function formatProjectDisplayName(projectDisplayName: string | null): string {
  const normalizedProjectDisplayName = projectDisplayName?.trim() ?? "";
  return normalizedProjectDisplayName || UNASSIGNED_PROJECT_LABEL;
}

function compareIsoDateTimeDesc(
  leftDateTimeText: string | null,
  rightDateTimeText: string | null
): number {
  const leftTimestamp = leftDateTimeText ? Date.parse(leftDateTimeText) : 0;
  const rightTimestamp = rightDateTimeText ? Date.parse(rightDateTimeText) : 0;
  return rightTimestamp - leftTimestamp;
}

export function ProjectTimelinePage() {
  const [projectList, setProjectList] = useState<Project[]>([]);
  const [taskList, setTaskList] = useState<Task[]>([]);
  const [selectedProjectCategory, setSelectedProjectCategory] = useState<string>(
    ALL_PROJECT_CATEGORIES_OPTION_VALUE
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string>(
    ALL_PROJECTS_OPTION_VALUE
  );
  const [selectedTimelineStatusList, setSelectedTimelineStatusList] = useState<
    TaskLifecycleStatus[]
  >(PROJECT_TIMELINE_DEFAULT_STATUS_FILTER_LIST);
  const [startDateText, setStartDateText] = useState<string>("");
  const [endDateText, setEndDateText] = useState<string>("");
  const [timelineEntryList, setTimelineEntryList] = useState<ProjectTimelineEntry[]>([]);
  const [selectedTimelineTaskId, setSelectedTimelineTaskId] = useState<string>("");
  const [selectedTimelineTaskDetail, setSelectedTimelineTaskDetail] =
    useState<ProjectTimelineTaskDetail | null>(null);
  const [summaryResult, setSummaryResult] = useState<ProjectTimelineSummary | null>(null);
  const [targetTaskId, setTargetTaskId] = useState<string>("");
  const [referenceNoteText, setReferenceNoteText] = useState<string>("");
  const [appendToRequirementBrief, setAppendToRequirementBrief] = useState<boolean>(true);
  const [loadingTimeline, setLoadingTimeline] = useState<boolean>(false);
  const [loadingTaskDetail, setLoadingTaskDetail] = useState<boolean>(false);
  const [runningSummary, setRunningSummary] = useState<boolean>(false);
  const [busyCreatingReference, setBusyCreatingReference] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const selectedProjectIdForQuery =
    selectedProjectId === ALL_PROJECTS_OPTION_VALUE ? null : selectedProjectId;
  const selectedProjectCategoryForQuery =
    selectedProjectCategory === ALL_PROJECT_CATEGORIES_OPTION_VALUE
      ? null
      : selectedProjectCategory;

  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const [projectResponse, taskResponse] = await Promise.all([
          projectApi.list(),
          taskApi.list(),
        ]);
        setProjectList(projectResponse);
        setTaskList(taskResponse);
      } catch (loadError) {
        setErrorMessage(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load project timeline base data."
        );
      }
    };

    void loadInitialData();
  }, []);

  const projectCategoryOptionList = useMemo(() => {
    const projectCategorySet = new Set<string>();
    for (const projectItem of projectList) {
      const normalizedProjectCategory = projectItem.project_category?.trim() ?? "";
      if (normalizedProjectCategory) {
        projectCategorySet.add(normalizedProjectCategory);
      }
    }
    return Array.from(projectCategorySet).sort((leftCategory, rightCategory) =>
      leftCategory.localeCompare(rightCategory, "zh-CN")
    );
  }, [projectList]);

  const filteredProjectList = useMemo(
    () =>
      projectList.filter((projectItem) => {
        if (selectedProjectCategoryForQuery === null) {
          return true;
        }
        return projectItem.project_category === selectedProjectCategoryForQuery;
      }),
    [projectList, selectedProjectCategoryForQuery]
  );

  useEffect(() => {
    if (selectedProjectId === ALL_PROJECTS_OPTION_VALUE) {
      return;
    }
    if (filteredProjectList.some((projectItem) => projectItem.id === selectedProjectId)) {
      return;
    }
    setSelectedProjectId(ALL_PROJECTS_OPTION_VALUE);
  }, [filteredProjectList, selectedProjectId]);

  useEffect(() => {
    const loadProjectTimeline = async () => {
      if (projectList.length === 0) {
        setTimelineEntryList([]);
        setSelectedTimelineTaskId("");
        setSelectedTimelineTaskDetail(null);
        return;
      }
      try {
        setLoadingTimeline(true);
        const projectTimelineEntryList = await chronicleApi.getProjectTimeline({
          project_id: selectedProjectIdForQuery,
          project_category: selectedProjectCategoryForQuery,
          lifecycle_status: selectedTimelineStatusList,
          start_date: buildDateFilterIsoText(startDateText, "start"),
          end_date: buildDateFilterIsoText(endDateText, "end"),
          limit: 500,
          offset: 0,
        });
        setTimelineEntryList(projectTimelineEntryList);
        if (
          selectedTimelineTaskId &&
          !projectTimelineEntryList.some(
            (timelineEntry) => timelineEntry.task_id === selectedTimelineTaskId
          )
        ) {
          setSelectedTimelineTaskId("");
          setSelectedTimelineTaskDetail(null);
        }
      } catch (loadError) {
        setErrorMessage(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load project timeline."
        );
      } finally {
        setLoadingTimeline(false);
      }
    };

    void loadProjectTimeline();
  }, [
    endDateText,
    projectList.length,
    selectedProjectCategoryForQuery,
    selectedProjectIdForQuery,
    selectedTimelineStatusList,
    selectedTimelineTaskId,
    startDateText,
  ]);

  useEffect(() => {
    const loadTaskDetail = async () => {
      if (!selectedTimelineTaskId) {
        setSelectedTimelineTaskDetail(null);
        return;
      }
      try {
        setLoadingTaskDetail(true);
        const taskDetail = await chronicleApi.getProjectTimelineTaskDetail(
          selectedTimelineTaskId
        );
        setSelectedTimelineTaskDetail(taskDetail);
      } catch (loadError) {
        setErrorMessage(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load task timeline detail."
        );
      } finally {
        setLoadingTaskDetail(false);
      }
    };

    void loadTaskDetail();
  }, [selectedTimelineTaskId]);

  useEffect(() => {
    setSummaryResult(null);
  }, [
    endDateText,
    selectedProjectCategoryForQuery,
    selectedProjectIdForQuery,
    selectedTimelineStatusList,
    startDateText,
  ]);

  const referenceProjectId =
    selectedTimelineTaskDetail?.task.project_id ?? selectedProjectIdForQuery;

  const availableTargetTaskList = useMemo(() => {
    if (!referenceProjectId) {
      return [];
    }
    return taskList.filter((taskItem) => {
      if (taskItem.project_id !== referenceProjectId) {
        return false;
      }
      if (selectedTimelineTaskId && taskItem.id === selectedTimelineTaskId) {
        return false;
      }
      return (
        taskItem.lifecycle_status !== TaskLifecycleStatus.CLOSED &&
        taskItem.lifecycle_status !== TaskLifecycleStatus.DELETED &&
        taskItem.lifecycle_status !== TaskLifecycleStatus.ABANDONED
      );
    });
  }, [referenceProjectId, selectedTimelineTaskId, taskList]);

  useEffect(() => {
    if (
      targetTaskId &&
      availableTargetTaskList.some((taskItem) => taskItem.id === targetTaskId)
    ) {
      return;
    }
    setTargetTaskId(availableTargetTaskList[0]?.id ?? "");
  }, [availableTargetTaskList, targetTaskId]);

  const timelineCategorySectionList = useMemo(() => {
    const timelineCategorySectionMap = new Map<
      string,
      {
        categoryLabel: string;
        entryList: ProjectTimelineEntry[];
        projectIdSet: Set<string>;
        totalLogs: number;
        bugCount: number;
        fixCount: number;
        lastActivityAt: string | null;
      }
    >();

    for (const timelineEntry of timelineEntryList) {
      const categoryLabel = formatProjectCategoryLabel(timelineEntry.project_category);
      const existingSection = timelineCategorySectionMap.get(categoryLabel);
      if (existingSection) {
        existingSection.entryList.push(timelineEntry);
        existingSection.projectIdSet.add(timelineEntry.project_id);
        existingSection.totalLogs += timelineEntry.total_logs;
        existingSection.bugCount += timelineEntry.bug_count;
        existingSection.fixCount += timelineEntry.fix_count;
        if (
          compareIsoDateTimeDesc(
            timelineEntry.last_activity_at,
            existingSection.lastActivityAt
          ) < 0
        ) {
          existingSection.lastActivityAt = timelineEntry.last_activity_at;
        }
        continue;
      }

      timelineCategorySectionMap.set(categoryLabel, {
        categoryLabel,
        entryList: [timelineEntry],
        projectIdSet: new Set([timelineEntry.project_id]),
        totalLogs: timelineEntry.total_logs,
        bugCount: timelineEntry.bug_count,
        fixCount: timelineEntry.fix_count,
        lastActivityAt: timelineEntry.last_activity_at,
      });
    }

    const timelineCategorySectionListValue: TimelineCategorySection[] = [];
    for (const timelineCategorySection of timelineCategorySectionMap.values()) {
      timelineCategorySectionListValue.push({
        categoryLabel: timelineCategorySection.categoryLabel,
        entryList: timelineCategorySection.entryList,
        projectCount: timelineCategorySection.projectIdSet.size,
        totalLogs: timelineCategorySection.totalLogs,
        bugCount: timelineCategorySection.bugCount,
        fixCount: timelineCategorySection.fixCount,
        lastActivityAt: timelineCategorySection.lastActivityAt,
      });
    }

    timelineCategorySectionListValue.sort((leftSection, rightSection) =>
      compareIsoDateTimeDesc(leftSection.lastActivityAt, rightSection.lastActivityAt)
    );
    return timelineCategorySectionListValue;
  }, [timelineEntryList]);

  const handleToggleLifecycleStatus = (statusValue: TaskLifecycleStatus) => {
    setSelectedTimelineStatusList((previousStatusList) => {
      if (previousStatusList.includes(statusValue)) {
        const nextStatusList = previousStatusList.filter(
          (existingStatusValue) => existingStatusValue !== statusValue
        );
        return nextStatusList.length > 0
          ? nextStatusList
          : PROJECT_TIMELINE_DEFAULT_STATUS_FILTER_LIST;
      }
      return [...previousStatusList, statusValue];
    });
  };

  const handleRunSummary = async () => {
    if (projectList.length === 0) {
      return;
    }
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      setRunningSummary(true);
      const summaryResponse = await chronicleApi.summarizeProjectTimeline({
        project_id: selectedProjectIdForQuery,
        project_category: selectedProjectCategoryForQuery,
        lifecycle_status_list: selectedTimelineStatusList,
        start_date: buildDateFilterIsoText(startDateText, "start"),
        end_date: buildDateFilterIsoText(endDateText, "end"),
        summary_focus: "progress",
      });
      setSummaryResult(summaryResponse);
    } catch (summaryError) {
      setErrorMessage(
        summaryError instanceof Error
          ? summaryError.message
          : "Failed to summarize project timeline."
      );
    } finally {
      setRunningSummary(false);
    }
  };

  const handleCreateReference = async () => {
    if (!selectedTimelineTaskId || !targetTaskId) {
      return;
    }
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      setBusyCreatingReference(true);
      const referenceResponse = await taskApi.createReference(targetTaskId, {
        source_task_id: selectedTimelineTaskId,
        append_to_requirement_brief: appendToRequirementBrief,
        reference_note: referenceNoteText.trim() || null,
      });
      setSuccessMessage(
        `已将历史任务 ${referenceResponse.source_task_id.slice(
          0,
          8
        )} 引用到当前需求。`
      );
    } catch (referenceError) {
      setErrorMessage(
        referenceError instanceof Error
          ? referenceError.message
          : "Failed to reference the historical requirement."
      );
    } finally {
      setBusyCreatingReference(false);
    }
  };

  return (
    <div className="ptl-page">
      <header className="ptl-header">
        <div className="ptl-header__copy">
          <h1>项目时间线管理</h1>
          <p>按项目类别或单项目回看需求与日志，支持历史需求引用与结构化总结。</p>
        </div>
        <a className="ptl-header__back-link" href="/">
          返回主工作台
        </a>
      </header>

      <section className="ptl-controls">
        <label>
          项目类别
          <select
            value={selectedProjectCategory}
            onChange={(event) => setSelectedProjectCategory(event.target.value)}
          >
            <option value={ALL_PROJECT_CATEGORIES_OPTION_VALUE}>全部类别</option>
            {projectCategoryOptionList.map((projectCategory) => (
              <option key={projectCategory} value={projectCategory}>
                {projectCategory}
              </option>
            ))}
          </select>
        </label>

        <label>
          项目
          <select
            value={selectedProjectId}
            onChange={(event) => setSelectedProjectId(event.target.value)}
          >
            <option value={ALL_PROJECTS_OPTION_VALUE}>全部项目</option>
            {filteredProjectList.map((projectItem) => (
              <option key={projectItem.id} value={projectItem.id}>
                {projectItem.display_name}
                {projectItem.project_category
                  ? ` · ${projectItem.project_category}`
                  : ""}
              </option>
            ))}
          </select>
        </label>

        <label>
          开始日期
          <input
            type="date"
            value={startDateText}
            onChange={(event) => setStartDateText(event.target.value)}
          />
        </label>

        <label>
          结束日期
          <input
            type="date"
            value={endDateText}
            onChange={(event) => setEndDateText(event.target.value)}
          />
        </label>

        <button
          type="button"
          className="ptl-controls__summary-btn"
          disabled={projectList.length === 0 || runningSummary}
          onClick={() => {
            void handleRunSummary();
          }}
        >
          {runningSummary ? "总结中..." : "AI 总结"}
        </button>
      </section>

      <section className="ptl-status-filter">
        {PROJECT_TIMELINE_DEFAULT_STATUS_FILTER_LIST.map((statusValue) => (
          <label key={statusValue} className="ptl-status-filter__item">
            <input
              type="checkbox"
              checked={selectedTimelineStatusList.includes(statusValue)}
              onChange={() => handleToggleLifecycleStatus(statusValue)}
            />
            <span>{statusValue}</span>
          </label>
        ))}
      </section>

      {errorMessage ? <div className="ptl-message ptl-message--error">{errorMessage}</div> : null}
      {successMessage ? (
        <div className="ptl-message ptl-message--success">{successMessage}</div>
      ) : null}

      {timelineCategorySectionList.length > 0 ? (
        <section className="ptl-overview">
          {timelineCategorySectionList.map((timelineCategorySection) => (
            <article
              key={timelineCategorySection.categoryLabel}
              className="ptl-overview__card"
            >
              <span className="ptl-overview__label">
                {timelineCategorySection.categoryLabel}
              </span>
              <strong>{timelineCategorySection.entryList.length} 个任务</strong>
              <span>{timelineCategorySection.projectCount} 个项目</span>
              <span>日志 {timelineCategorySection.totalLogs} 条</span>
              <span>
                BUG {timelineCategorySection.bugCount} · FIX{" "}
                {timelineCategorySection.fixCount}
              </span>
            </article>
          ))}
        </section>
      ) : null}

      <main className="ptl-layout">
        <section className="ptl-list">
          <h2>项目时间线</h2>
          {loadingTimeline ? <p>加载中...</p> : null}
          {!loadingTimeline && timelineEntryList.length === 0 ? <p>暂无时间线记录。</p> : null}
          {timelineCategorySectionList.map((timelineCategorySection) => (
            <div
              key={timelineCategorySection.categoryLabel}
              className="ptl-category-section"
            >
              <div className="ptl-category-section__header">
                <div>
                  <h3>{timelineCategorySection.categoryLabel}</h3>
                  <p>
                    {timelineCategorySection.projectCount} 个项目 ·{" "}
                    {timelineCategorySection.entryList.length} 个任务 · 日志{" "}
                    {timelineCategorySection.totalLogs} 条
                  </p>
                </div>
              </div>

              <ul>
                {timelineCategorySection.entryList.map((timelineEntry) => (
                  <li
                    key={timelineEntry.task_id}
                    className={
                      timelineEntry.task_id === selectedTimelineTaskId
                        ? "ptl-list__item ptl-list__item--active"
                        : "ptl-list__item"
                    }
                  >
                    <button
                      type="button"
                      onClick={() => setSelectedTimelineTaskId(timelineEntry.task_id)}
                    >
                      <strong>{timelineEntry.task_title}</strong>
                      <span>
                        {formatProjectDisplayName(timelineEntry.project_display_name)} ·{" "}
                        {timelineEntry.lifecycle_status} · {timelineEntry.workflow_stage}
                      </span>
                      <span>
                        日志 {timelineEntry.total_logs} 条 · BUG{" "}
                        {timelineEntry.bug_count} · FIX {timelineEntry.fix_count}
                      </span>
                      <span>最近活动 {formatDateTime(timelineEntry.last_activity_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>

        <section className="ptl-detail">
          <h2>详情</h2>
          {loadingTaskDetail ? <p>加载详情中...</p> : null}
          {!loadingTaskDetail && !selectedTimelineTaskDetail ? (
            <p>请选择左侧任务查看详情。</p>
          ) : null}

          {selectedTimelineTaskDetail ? (
            <div className="ptl-detail__panel">
              <h3>{selectedTimelineTaskDetail.task.title}</h3>
              <p>
                {selectedTimelineTaskDetail.task.lifecycle_status} ·{" "}
                {selectedTimelineTaskDetail.task.workflow_stage}
              </p>
              <p className="ptl-detail__submeta">
                {formatProjectDisplayName(
                  selectedTimelineTaskDetail.task.project_display_name
                )}{" "}
                ·{" "}
                {formatProjectCategoryLabel(
                  selectedTimelineTaskDetail.task.project_category
                )}
              </p>
              <p>创建时间：{formatDateTime(selectedTimelineTaskDetail.task.created_at)}</p>

              <div className="ptl-detail__block">
                <h4>Requirement Snapshot</h4>
                <pre>
                  {selectedTimelineTaskDetail.requirement_snapshot ||
                    "No requirement snapshot."}
                </pre>
              </div>

              <div className="ptl-detail__block">
                <h4>PRD Snapshot</h4>
                {selectedTimelineTaskDetail.prd_snapshot ? (
                  <>
                    <p>
                      来源：{selectedTimelineTaskDetail.prd_snapshot.source_path || "N/A"}
                    </p>
                    <pre>{selectedTimelineTaskDetail.prd_snapshot.content_markdown}</pre>
                  </>
                ) : (
                  <p>暂无 PRD 快照。</p>
                )}
              </div>

              <div className="ptl-detail__block">
                <h4>Planning with files</h4>
                {selectedTimelineTaskDetail.planning_snapshot ? (
                  <>
                    <p>
                      来源：
                      {selectedTimelineTaskDetail.planning_snapshot.source_path || "N/A"}
                    </p>
                    {selectedTimelineTaskDetail.planning_snapshot.file_manifest.length > 0 ? (
                      <ul className="ptl-file-list">
                        {selectedTimelineTaskDetail.planning_snapshot.file_manifest.map(
                          (filePath) => (
                            <li key={filePath}>{filePath}</li>
                          )
                        )}
                      </ul>
                    ) : null}
                    <pre>{selectedTimelineTaskDetail.planning_snapshot.content_markdown}</pre>
                  </>
                ) : (
                  <p>暂无 planning with files 快照。</p>
                )}
              </div>

              <div className="ptl-detail__block">
                <h4>加入当前需求卡片</h4>
                <label>
                  目标需求（同项目）
                  <select
                    value={targetTaskId}
                    onChange={(event) => setTargetTaskId(event.target.value)}
                  >
                    <option value="">请选择目标需求</option>
                    {availableTargetTaskList.map((taskItem) => (
                      <option key={taskItem.id} value={taskItem.id}>
                        {taskItem.task_title}
                      </option>
                    ))}
                  </select>
                </label>
                {availableTargetTaskList.length === 0 ? (
                  <p>当前项目下暂无可引用的目标需求。</p>
                ) : null}
                <label>
                  引用备注
                  <textarea
                    value={referenceNoteText}
                    onChange={(event) => setReferenceNoteText(event.target.value)}
                    placeholder="可选：写入引用备注"
                  />
                </label>
                <label className="ptl-inline-checkbox">
                  <input
                    type="checkbox"
                    checked={appendToRequirementBrief}
                    onChange={(event) =>
                      setAppendToRequirementBrief(event.target.checked)
                    }
                  />
                  <span>同时追加到目标需求描述</span>
                </label>
                <button
                  type="button"
                  disabled={!targetTaskId || busyCreatingReference}
                  onClick={() => {
                    void handleCreateReference();
                  }}
                >
                  {busyCreatingReference ? "处理中..." : "加入当前需求卡片"}
                </button>
              </div>

              <div className="ptl-detail__block">
                <h4>日志预览</h4>
                <ul className="ptl-log-list">
                  {selectedTimelineTaskDetail.logs.map((timelineLogItem) => (
                    <li key={timelineLogItem.id}>
                      <span>{formatDateTime(timelineLogItem.created_at)}</span>
                      <span>{timelineLogItem.state_tag}</span>
                      <pre>{timelineLogItem.text_content || "无正文内容。"}</pre>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </section>
      </main>

      {summaryResult ? (
        <section className="ptl-summary">
          <h2>AI 总结</h2>
          <p>{summaryResult.summary_text}</p>

          <h3>里程碑</h3>
          <ul>
            {summaryResult.milestones.map((milestoneText) => (
              <li key={milestoneText}>{milestoneText}</li>
            ))}
          </ul>

          <h3>风险</h3>
          <ul>
            {summaryResult.risks.map((riskText) => (
              <li key={riskText}>{riskText}</li>
            ))}
          </ul>

          <h3>下一步建议</h3>
          <ul>
            {summaryResult.next_actions.map((nextActionText) => (
              <li key={nextActionText}>{nextActionText}</li>
            ))}
          </ul>

          <h3>来源任务</h3>
          <p>{summaryResult.source_task_ids.join(", ") || "无"}</p>
        </section>
      ) : null}
    </div>
  );
}
