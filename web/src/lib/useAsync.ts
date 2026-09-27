import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
  set: (value: T) => void;
}

/**
 * The whole data-fetching story: run an async function on mount, keep its
 * result, expose its error, and let a caller reload it. No cache library,
 * because a cache that outlives a request would let the console render a
 * permission the server has since taken away.
 */
export function useAsync<T>(run: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const ticket = ++latest.current;
    setLoading(true);
    setError(null);
    run()
      .then((value) => {
        if (latest.current !== ticket) return;
        setData(value);
        setLoading(false);
      })
      .catch((cause: unknown) => {
        if (latest.current !== ticket) return;
        setError(cause);
        setLoading(false);
      });
    // `run` is a fresh closure each render; `deps` is the real dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, error, loading, reload, set: setData };
}
