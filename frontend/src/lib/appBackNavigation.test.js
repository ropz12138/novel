import { describe, expect, it, vi } from "vitest";

import { exitNativeApp, subscribeAppBack, subscribeAppResume } from "./appBackNavigation";


describe("appBackNavigation", () => {
  it("subscribes to the native back button and removes the listener", async () => {
    const remove = vi.fn();
    const onBack = vi.fn();
    let nativeListener;
    const plugin = {
      addListener: vi.fn(async (_eventName, listener) => {
        nativeListener = listener;
        return { remove };
      }),
    };

    const unsubscribe = await subscribeAppBack(onBack, plugin);
    nativeListener();
    expect(onBack).toHaveBeenCalledOnce();

    await unsubscribe();
    expect(remove).toHaveBeenCalledOnce();
  });

  it("exits through the native plugin", async () => {
    const plugin = { exitApp: vi.fn().mockResolvedValue(undefined) };

    await exitNativeApp(plugin);

    expect(plugin.exitApp).toHaveBeenCalledOnce();
  });

  it("subscribes to native foreground resumes and removes the listener", async () => {
    const remove = vi.fn();
    const onResume = vi.fn();
    let nativeListener;
    const plugin = {
      addListener: vi.fn(async (eventName, listener) => {
        expect(eventName).toBe("appResumed");
        nativeListener = listener;
        return { remove };
      }),
    };

    const unsubscribe = await subscribeAppResume(onResume, plugin);
    nativeListener();
    expect(onResume).toHaveBeenCalledOnce();

    await unsubscribe();
    expect(remove).toHaveBeenCalledOnce();
  });
});
