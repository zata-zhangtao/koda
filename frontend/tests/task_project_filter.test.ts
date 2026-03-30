import assert from "node:assert/strict";

import type { Project } from "../src/types.ts";
import {
  ALL_TASK_PROJECT_FILTER_VALUE,
  UNLINKED_TASK_PROJECT_FILTER_VALUE,
  buildTaskProjectDisplayLabelMap,
  buildTaskProjectFilterOptionList,
  buildTaskProjectFilterRequestOptions,
  createNextTaskProjectRequestToken,
  deriveCreateRequirementProjectIdFromFilter,
  getTaskProjectFilterDisplayLabel,
  normalizeTaskProjectFilterValue,
  shouldCommitTaskProjectMetadataResponse,
  shouldCommitTaskProjectResponse,
  shouldReloadTaskProjectFilterData,
} from "../src/utils/task_project_filter.ts";

const projectList: Project[] = [
  {
    id: "project-alpha",
    display_name: "Alpha",
    repo_path: "/tmp/alpha",
    repo_remote_url: null,
    repo_head_commit_hash: null,
    current_repo_remote_url: null,
    current_repo_head_commit_hash: null,
    description: null,
    is_repo_path_valid: true,
    is_repo_remote_consistent: true,
    is_repo_head_consistent: true,
    repo_consistency_note: null,
    created_at: "2026-03-30T10:00:00+08:00",
  },
];

const duplicateNameProjectList: Project[] = [
  {
    ...projectList[0],
    id: "11111111-alpha",
    repo_path: "/tmp/workspaces/alpha-api",
  },
  {
    ...projectList[0],
    id: "22222222-alpha",
    repo_path: "C:\\repos\\alpha-web",
  },
];

assert.deepEqual(buildTaskProjectFilterRequestOptions(ALL_TASK_PROJECT_FILTER_VALUE), {});
assert.deepEqual(buildTaskProjectFilterRequestOptions(UNLINKED_TASK_PROJECT_FILTER_VALUE), {
  unlinkedOnly: true,
});
assert.deepEqual(buildTaskProjectFilterRequestOptions("project-alpha"), {
  projectId: "project-alpha",
});
assert.equal(
  shouldReloadTaskProjectFilterData(
    ALL_TASK_PROJECT_FILTER_VALUE,
    "project-alpha",
    false
  ),
  true
);
assert.equal(
  shouldReloadTaskProjectFilterData(
    ALL_TASK_PROJECT_FILTER_VALUE,
    ALL_TASK_PROJECT_FILTER_VALUE,
    false
  ),
  false
);
assert.equal(
  shouldReloadTaskProjectFilterData(
    ALL_TASK_PROJECT_FILTER_VALUE,
    "project-alpha",
    true
  ),
  false
);
assert.equal(
  shouldReloadTaskProjectFilterData(null, "project-alpha", false),
  false
);
assert.equal(createNextTaskProjectRequestToken(0), 1);
assert.equal(createNextTaskProjectRequestToken(1), 2);
assert.equal(
  shouldCommitTaskProjectResponse(
    2,
    1,
    ALL_TASK_PROJECT_FILTER_VALUE,
    "project-alpha"
  ),
  false
);
assert.equal(
  shouldCommitTaskProjectResponse(
    1,
    1,
    ALL_TASK_PROJECT_FILTER_VALUE,
    "project-alpha"
  ),
  false
);
assert.equal(
  shouldCommitTaskProjectResponse(
    4,
    4,
    "project-alpha",
    "project-alpha"
  ),
  true
);
assert.equal(
  shouldCommitTaskProjectMetadataResponse(
    5,
    4,
    "project-beta",
    "project-alpha",
    true
  ),
  false
);
assert.equal(
  shouldCommitTaskProjectMetadataResponse(
    5,
    5,
    "project-beta",
    "project-alpha",
    false
  ),
  false
);
assert.equal(
  shouldCommitTaskProjectMetadataResponse(
    5,
    5,
    "project-beta",
    "project-alpha",
    true
  ),
  true
);
assert.equal(
  shouldCommitTaskProjectMetadataResponse(
    5,
    5,
    "project-alpha",
    "project-alpha",
    false
  ),
  true
);

assert.equal(
  normalizeTaskProjectFilterValue(UNLINKED_TASK_PROJECT_FILTER_VALUE, projectList),
  UNLINKED_TASK_PROJECT_FILTER_VALUE
);
assert.equal(
  normalizeTaskProjectFilterValue("missing-project", projectList),
  ALL_TASK_PROJECT_FILTER_VALUE
);
assert.equal(
  normalizeTaskProjectFilterValue("project-alpha", projectList),
  "project-alpha"
);

assert.equal(deriveCreateRequirementProjectIdFromFilter(ALL_TASK_PROJECT_FILTER_VALUE), null);
assert.equal(
  deriveCreateRequirementProjectIdFromFilter(UNLINKED_TASK_PROJECT_FILTER_VALUE),
  null
);
assert.equal(
  deriveCreateRequirementProjectIdFromFilter("project-alpha"),
  "project-alpha"
);

assert.equal(
  getTaskProjectFilterDisplayLabel(ALL_TASK_PROJECT_FILTER_VALUE, projectList),
  "全部项目"
);
assert.equal(
  getTaskProjectFilterDisplayLabel(UNLINKED_TASK_PROJECT_FILTER_VALUE, projectList),
  "未关联项目"
);
assert.equal(
  getTaskProjectFilterDisplayLabel("project-alpha", projectList),
  "Alpha"
);
assert.deepEqual(buildTaskProjectDisplayLabelMap(projectList), {
  "project-alpha": "Alpha",
});
assert.deepEqual(buildTaskProjectDisplayLabelMap(duplicateNameProjectList), {
  "11111111-alpha": "Alpha (alpha-api / 11111111)",
  "22222222-alpha": "Alpha (alpha-web / 22222222)",
});
assert.equal(
  getTaskProjectFilterDisplayLabel("11111111-alpha", duplicateNameProjectList),
  "Alpha (alpha-api / 11111111)"
);

const taskProjectFilterOptionList = buildTaskProjectFilterOptionList(projectList);
assert.deepEqual(
  taskProjectFilterOptionList.map((taskProjectFilterOption) => taskProjectFilterOption.label),
  ["全部项目", "未关联项目", "Alpha"]
);
const duplicateNameTaskProjectFilterOptionList = buildTaskProjectFilterOptionList(
  duplicateNameProjectList
);
assert.deepEqual(
  duplicateNameTaskProjectFilterOptionList.map(
    (taskProjectFilterOption) => taskProjectFilterOption.label
  ),
  [
    "全部项目",
    "未关联项目",
    "Alpha (alpha-api / 11111111)",
    "Alpha (alpha-web / 22222222)",
  ]
);

console.log("task_project_filter.test.ts: PASS");
