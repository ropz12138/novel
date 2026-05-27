import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Smart auto-scroll hook: auto-scrolls to bottom during streaming,
 * but respects user scroll and stops forcing when user scrolls up.
 *
 * @param {React.RefObject} scrollContainerRef - ref to the scrollable container
 * @param {Array} deps - dependency array that triggers content changes
 * @returns {{ stickToBottom: boolean, scrollToBottom: () => void }}
 */
export function useSmartScroll(scrollContainerRef, deps) {
  const [stickToBottom, setStickToBottom] = useState(true);
  const stickRef = useRef(true);
  const isAutoScrolling = useRef(false);

  const checkIfAtBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return true;
    const threshold = 80;
    return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  }, [scrollContainerRef]);

  // Detect user scroll vs programmatic scroll
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;

    const handleScroll = () => {
      if (isAutoScrolling.current) {
        isAutoScrolling.current = false;
        return;
      }
      const atBottom = checkIfAtBottom();
      if (!atBottom && stickRef.current) {
        stickRef.current = false;
        setStickToBottom(false);
      }
    };

    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [scrollContainerRef, checkIfAtBottom]);

  // Auto-scroll when content changes (if sticking to bottom)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!stickRef.current) return;
    const el = scrollContainerRef.current;
    if (!el) return;
    isAutoScrolling.current = true;
    el.scrollTop = el.scrollHeight;
  }, deps);

  const scrollToBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    stickRef.current = true;
    setStickToBottom(true);
    isAutoScrolling.current = true;
    el.scrollTop = el.scrollHeight;
  }, [scrollContainerRef]);

  // Re-stick when new user message is sent (running becomes true)
  // This is handled by the parent via scrollToBottom

  return { stickToBottom, scrollToBottom };
}
