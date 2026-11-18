"use client";
import { useCallback, useEffect, useState } from "react";

import { apiFetch, explain, type Category, type Page } from "./api";
import { config } from "./config";
import { useAuth } from "./auth";

/** Load data from the API; `reload` re-runs the request. */
export function useLoad<T>(path: string | null) {
  const { getToken, state } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path || state.status !== "ready") return;
    let cancelled = false;
    setError(null);
    apiFetch<T>(getToken, path)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(explain(e)));
    return () => {
      cancelled = true;
    };
  }, [path, tick, getToken, state.status]);

  return { data, error, reload };
}

/** A write action with busy/error state. */
export function useAction() {
  const { getToken } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async <T,>(path: string, method: "POST" | "PATCH", body: unknown): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await apiFetch<T>(getToken, path, { method, body: JSON.stringify(body) });
    } catch (e) {
      setError(explain(e));
      return null;
    } finally {
      setBusy(false);
    }
  }, [getToken]);
  return { run, busy, error, setError };
}

/** Category names from the public reference endpoint (no sign-in needed). */
export function useCategoryNames(): Record<string, string> {
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    fetch(`${config.apiBase}/incident-categories`)
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d: Page<Category>) => setNames(Object.fromEntries(d.items.map((c) => [c.code, c.name]))))
      .catch(() => undefined);
  }, []);
  return names;
}
