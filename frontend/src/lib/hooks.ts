"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getJob, getMetadata, getSceneManifest, sceneSummary, subscribeJob } from "./api/survey";
import type { JobStatus, LogLine, SceneManifest, SceneMetadata, SceneSummary } from "./sceneTypes";

const TERMINAL = new Set(["READY", "FAILED"]);

/** Live job state: SSE while running, one plain fetch when finished. */
export function useJobLive(jobId: string) {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const firstEvent = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const fresh = await getJob(jobId);
      setJob(fresh);
      setLogs(fresh.logs);
      return fresh;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the job.");
      return null;
    }
  }, [jobId]);

  useEffect(() => {
    let unsubscribe: (() => void) | undefined;
    let poll: ReturnType<typeof setInterval> | undefined;
    let cancelled = false;
    firstEvent.current = true;

    const startPolling = () => {
      poll = setInterval(async () => {
        const fresh = await refresh();
        if (fresh && TERMINAL.has(fresh.stage) && poll) clearInterval(poll);
      }, 1500);
    };

    (async () => {
      const initial = await refresh();
      if (cancelled || !initial) return;
      if (TERMINAL.has(initial.stage) || initial.stage === "UPLOADED") return;
      unsubscribe = subscribeJob(
        jobId,
        (update) => {
          firstEvent.current = false;
          setJob(update);
          setLogs((previous) => (previous.length === 0 || update.logs.length > 100 ? update.logs : [...previous, ...update.logs]));
        },
        () => void refresh(),
        startPolling,
      );
    })();

    return () => {
      cancelled = true;
      unsubscribe?.();
      if (poll) clearInterval(poll);
    };
  }, [jobId, refresh]);

  return { job, logs, error, refresh, setJob };
}

/** Everything a finished scene needs: metadata, manifest, statistics. Pass `null` while the
 * scene isn't ready yet -- the hook then skips fetching instead of hitting the API with a
 * job id that can't resolve. */
export function useScene(jobId: string | null) {
  const [metadata, setMetadata] = useState<SceneMetadata | null>(null);
  const [manifest, setManifest] = useState<SceneManifest | null>(null);
  const [summary, setSummary] = useState<SceneSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (jobId === null) {
      setMetadata(null);
      setManifest(null);
      setSummary(null);
      setError(null);
      setLoading(true);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all([getMetadata(jobId), getSceneManifest(jobId), sceneSummary(jobId)])
      .then(([meta, scene, stats]) => {
        if (cancelled) return;
        setMetadata(meta);
        setManifest(scene);
        setSummary(stats);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "This scene is not ready yet.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  return { metadata, manifest, summary, error, loading };
}
