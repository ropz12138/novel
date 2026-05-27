import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useSmartScroll } from "../hooks/useSmartScroll";

describe("useSmartScroll", () => {
  function createMockContainer() {
    const el = {
      scrollHeight: 1000,
      scrollTop: 900,
      clientHeight: 100,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    const ref = { current: el };
    return { ref, el };
  }

  it("defaults to stickToBottom=true", () => {
    const { ref } = createMockContainer();
    const { result } = renderHook(() => useSmartScroll(ref, []));
    expect(result.current.stickToBottom).toBe(true);
  });

  it("exposes scrollToBottom function", () => {
    const { ref } = createMockContainer();
    const { result } = renderHook(() => useSmartScroll(ref, []));
    expect(typeof result.current.scrollToBottom).toBe("function");
  });

  it("scrollToBottom sets stickToBottom to true", async () => {
    const { ref, el } = createMockContainer();
    const { result } = renderHook(() => useSmartScroll(ref, []));

    act(() => {
      result.current.scrollToBottom();
    });

    expect(result.current.stickToBottom).toBe(true);
    expect(el.scrollTop).toBe(el.scrollHeight);
  });

  it("registers scroll event listener on mount", () => {
    const { ref, el } = createMockContainer();
    renderHook(() => useSmartScroll(ref, []));
    expect(el.addEventListener).toHaveBeenCalledWith("scroll", expect.any(Function), { passive: true });
  });

  it("removes scroll event listener on unmount", () => {
    const { ref, el } = createMockContainer();
    const { unmount } = renderHook(() => useSmartScroll(ref, []));
    unmount();
    expect(el.removeEventListener).toHaveBeenCalledWith("scroll", expect.any(Function));
  });
});
