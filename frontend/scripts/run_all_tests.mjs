import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFilePath = fileURLToPath(import.meta.url);
const scriptsDirectoryPath = path.dirname(currentFilePath);
const frontendDirectoryPath = path.resolve(scriptsDirectoryPath, "..");
const testsDirectoryPath = path.join(frontendDirectoryPath, "tests");

const discoveredTestFileNames = readdirSync(testsDirectoryPath)
  .filter((entryName) => entryName.endsWith(".test.ts"))
  .sort();

if (discoveredTestFileNames.length === 0) {
  console.error("No test files found in frontend/tests.");
  process.exit(1);
}

let observedFailureCount = 0;

for (const discoveredTestFileName of discoveredTestFileNames) {
  const relativeTestFilePath = path.join("tests", discoveredTestFileName);
  const spawnedTestProcess = spawnSync(
    process.execPath,
    [
      "--experimental-strip-types",
      "--experimental-specifier-resolution=node",
      relativeTestFilePath,
    ],
    {
      cwd: frontendDirectoryPath,
      stdio: "inherit",
    },
  );

  if (spawnedTestProcess.status !== 0) {
    observedFailureCount += 1;
  }
}

if (observedFailureCount > 0) {
  process.exit(1);
}
