import { useRef, useCallback } from "react";

export function useDebouncedRefresh(ref, delay = 300) {
  const timerRef = useRef(null);

  const trigger = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      ref.current?.refresh?.();
    }, delay);
  }, [ref, delay]);

  return trigger;
}
