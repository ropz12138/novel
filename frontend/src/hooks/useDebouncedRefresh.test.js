import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDebouncedRefresh } from "./useDebouncedRefresh";

describe("useDebouncedRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls ref.current.refresh after the specified delay", async () => {
    const refresh = vi.fn();
    const ref = { current: { refresh } };
    const { result } = renderHook(() => useDebouncedRefresh(ref, 300));

    result.current();
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("debounces multiple rapid calls into a single refresh", async () => {
    const refresh = vi.fn();
    const ref = { current: { refresh } };
    const { result } = renderHook(() => useDebouncedRefresh(ref, 300));

    result.current();
    result.current();
    result.current();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("resets the timer when called again before delay elapses", async () => {
    const refresh = vi.fn();
    const ref = { current: { refresh } };
    const { result } = renderHook(() => useDebouncedRefresh(ref, 300));

    result.current();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(refresh).not.toHaveBeenCalled();

    result.current();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("handles missing ref.current gracefully", async () => {
    const ref = { current: null };
    const { result } = renderHook(() => useDebouncedRefresh(ref, 300));

    result.current();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
  });

  it("handles ref.current without a refresh method gracefully", async () => {
    const ref = { current: {} };
    const { result } = renderHook(() => useDebouncedRefresh(ref, 300));

    result.current();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
  });

  it("uses 300ms as default delay", async () => {
    const refresh = vi.fn();
    const ref = { current: { refresh } };
    const { result } = renderHook(() => useDebouncedRefresh(ref));

    result.current();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
