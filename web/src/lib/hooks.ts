import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** GET a URL with loading / error state. `pollMs` re-fetches while `shouldPoll(data)` is true. */
export function useApi<T>(url: string | null, opts: { pollMs?: number; shouldPoll?: (d: T) => boolean } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!url);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const load = useCallback(async () => {
    if (!url) return;
    try {
      const d = await api.get<T>(url);
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let alive = true;
    setLoading(!!url);
    const tick = async () => {
      const d = await load();
      const { pollMs, shouldPoll } = optsRef.current;
      if (alive && pollMs && d && (!shouldPoll || shouldPoll(d))) timer = setTimeout(tick, pollMs);
    };
    tick();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [load]);

  return { data, error, loading, reload: load, setData };
}

export type Route = { page: string; params: URLSearchParams };

function parse(): Route {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [page, qs] = raw.split("?");
  return { page: page || "dashboard", params: new URLSearchParams(qs ?? "") };
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(page: string, params?: Record<string, string>) {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  window.location.hash = `/${page}${qs}`;
}
