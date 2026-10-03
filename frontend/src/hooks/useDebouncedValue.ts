"use client";

import { useEffect, useState } from "react";

/** Returns `value`, but only updates after `delayMs` of no further changes.
 * Used by the flood scenario's water-level slider so dragging doesn't fire a
 * network request on every pixel of movement. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
