/** API Hooks
 *
 * React hooks for data fetching
 */

import { useCallback, useEffect, useState } from "react";
import { logApi, runAccountApi, taskApi } from "../api/client";
import type { DevLog, RunAccount, Task } from "../types";

/** Hook for fetching current run account */
export function useRunAccount() {
  const [account, setAccount] = useState<RunAccount | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchAccount = useCallback(async () => {
    try {
      setLoading(true);
      const data = await runAccountApi.getCurrent();
      setAccount(data);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAccount();
  }, [fetchAccount]);

  return { account, loading, error, refetch: fetchAccount };
}

/** Hook for fetching tasks */
export function useTasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchTasks = useCallback(async () => {
    try {
      setLoading(true);
      const data = await taskApi.list();
      setTasks(data);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  return { tasks, loading, error, refetch: fetchTasks };
}

/** Hook for fetching logs */
export function useLogs(taskId?: string, limit = 100) {
  const [logs, setLogs] = useState<DevLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchLogs = useCallback(async () => {
    try {
      setLoading(true);
      const data = await logApi.list(taskId, limit);
      setLogs(data);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  }, [taskId, limit]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  return { logs, loading, error, refetch: fetchLogs };
}
