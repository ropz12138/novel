import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AppFloatingComposer from "./AppFloatingComposer";

describe("AppFloatingComposer", () => {
  it("shows the token count for each session including missing usage", () => {
    render(<AppFloatingComposer ready sessions={[
      { id: "s1", title: "已有对话", context_input_tokens: 12345 },
      { id: "s2", title: "新对话", context_input_tokens: null },
    ]} />);
    fireEvent.click(screen.getByRole("button", { name: "会话列表" }));
    expect(screen.getByText("【12,345】 tokens")).toBeDefined();
    expect(screen.getByText("【0】 tokens")).toBeDefined();
  });
  it("keeps Enter as a newline and sends only from the button", () => {
    const onSend = vi.fn();
    render(<AppFloatingComposer ready onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: "快捷创作指令" });
    expect(input.tagName).toBe("TEXTAREA");
    fireEvent.change(input, { target: { value: "第一行\n第二行" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "发送快捷指令" }));
    expect(onSend).toHaveBeenCalledWith("第一行\n第二行");
  });
  beforeEach(() => {
    vi.stubGlobal("PointerEvent", MouseEvent);
  });
  it("uses a capsule bar and opens sessions from the minus button", () => {
    const onNewSession = vi.fn();
    const onSelectSession = vi.fn();
    const onSend = vi.fn();
    render(
      <AppFloatingComposer
        ready
        sessions={[{ id: "s1", title: "上一轮对话" }]}
        currentSessionId="s1"
        onNewSession={onNewSession}
        onSelectSession={onSelectSession}
        onSend={onSend}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    expect(screen.getByTestId("app-floating-composer-bar").className).toContain("rounded-full");
    expect(screen.queryByRole("button", { name: "新建会话" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "会话列表" }));
    fireEvent.click(screen.getByRole("button", { name: "新对话" }));
    expect(onNewSession).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "会话列表" }));
    fireEvent.click(screen.getByRole("button", { name: "上一轮对话" }));
    expect(onSelectSession).toHaveBeenCalledWith({ id: "s1", title: "上一轮对话" });

    fireEvent.change(screen.getByRole("textbox", { name: "快捷创作指令" }), {
      target: { value: "继续写最新章节" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送快捷指令" }));
    expect(onSend).toHaveBeenCalledWith("继续写最新章节");
  });

  it("closes the session list when clicking outside", () => {
    render(
      <AppFloatingComposer
        ready
        sessions={[{ id: "s1", title: "上一轮对话" }]}
        onNewSession={vi.fn()}
        onSelectSession={vi.fn()}
        onSend={vi.fn()}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "会话列表" }));
    expect(screen.getByTestId("app-session-list")).toBeDefined();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByTestId("app-session-list")).toBeNull();
  });

  it("allows another message to be queued while streaming", () => {
    const onStop = vi.fn();
    const onSend = vi.fn();
    render(
      <AppFloatingComposer
        ready
        running
        streamLine="正在写第三段"
        pendingMessages={[{ id: "queued-1", content: "已经排队的任务" }]}
        onNewSession={vi.fn()}
        onSend={onSend}
        onStop={onStop}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    expect(screen.getByText("等待发送：已经排队的任务")).toBeDefined();

    const input = screen.getByRole("textbox", { name: "快捷创作指令" });
    fireEvent.change(input, { target: { value: "下一条任务" } });
    expect(screen.queryByRole("button", { name: "中止" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "发送快捷指令" }));
    expect(onSend).toHaveBeenCalledWith("下一条任务");
    expect(screen.queryByRole("button", { name: "发送快捷指令" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "中止" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("shows only the latest streaming line while running", () => {
    render(
      <AppFloatingComposer
        ready
        running
        streamLine="正在写第三段"
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    expect(screen.getByRole("textbox", { name: "快捷创作指令" })).toBeDefined();
    const preview = screen.getByTestId("app-composer-stream");
    expect(screen.getByTestId("app-floating-composer-bar").contains(preview)).toBe(true);
    expect(preview.parentElement.parentElement.contains(screen.getByRole("textbox", { name: "快捷创作指令" }))).toBe(true);
    expect(preview.textContent).toBe("正在写第三段");
    expect(preview.className).toContain("bg-slate-100");
    expect(preview.querySelector("span").className).toContain("text-[12px]");
  });

  it("shows streaming only while the input is blurred and empty", () => {
    render(
      <AppFloatingComposer
        ready
        running
        streamLine="正在写第三段"
        onSend={vi.fn()}
        onStop={vi.fn()}
      />,
    );

    const input = screen.getByRole("textbox", { name: "快捷创作指令" });
    expect(screen.getByTestId("app-composer-stream")).toBeDefined();

    fireEvent.focus(input);
    expect(screen.queryByTestId("app-composer-stream")).toBeNull();

    fireEvent.change(input, { target: { value: "补充人物反应" } });
    fireEvent.blur(input);
    expect(screen.queryByTestId("app-composer-stream")).toBeNull();

    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByTestId("app-composer-stream")).toBeDefined();
  });

  it("animates thinking status instead of treating it as user input", () => {
    render(
      <AppFloatingComposer
        ready
        running
        streamLine="AI 思考中"
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    expect(screen.getByRole("textbox", { name: "快捷创作指令" }).value).toBe("");
    const thinking = screen.getByTestId("app-composer-thinking");
    expect(thinking.textContent.replace(/\u00a0/g, " ")).toContain("AI 思考中");
    expect(thinking.querySelector(".app-composer-think-char")).toBeTruthy();
    expect(thinking.querySelector(".app-composer-think-dot")).toBeTruthy();
    expect(screen.getByTestId("app-floating-composer-bar").contains(thinking)).toBe(true);
    fireEvent.focus(screen.getByRole("textbox", { name: "快捷创作指令" }));
    expect(screen.queryByTestId("app-composer-thinking")).toBeNull();
  });

  it("animates reconnecting status the same way as thinking", () => {
    render(
      <AppFloatingComposer
        ready
        running
        streamLine="重连中..."
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    expect(screen.queryByTestId("app-composer-stream")).toBeNull();
    const thinking = screen.getByTestId("app-composer-thinking");
    expect(thinking.textContent.replace(/\u00a0/g, " ")).toContain("重连中...");
    expect(thinking.querySelector(".app-composer-think-char")).toBeTruthy();
    expect(thinking.querySelector(".app-composer-think-dot")).toBeTruthy();
  });

  it("keeps the Agent trigger beside the bar and leaves characters out of the composer", () => {
    render(
      <AppFloatingComposer
        ready
        agentCollapsed
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    const agent = screen.getByRole("button", { name: "展开Agent侧边栏" });
    expect(screen.queryByRole("button", { name: "展开角色与设定侧栏" })).toBeNull();
    expect(screen.getByTestId("app-floating-composer").contains(agent)).toBe(true);
    expect(screen.getByTestId("app-floating-composer-bar").contains(agent)).toBe(false);
  });

  it("keeps chapter review intensity above the input so the text row stays wide", () => {
    const onIntensityChange = vi.fn();
    render(
      <AppFloatingComposer
        ready
        intensity="low"
        onIntensityChange={onIntensityChange}
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    const slider = screen.getByRole("slider", { name: "快捷评审强度" });
    const bar = screen.getByTestId("app-floating-composer-bar");
    expect(bar.contains(slider)).toBe(false);
    expect(slider.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(slider.getAttribute("aria-valuetext")).toBe("low");

    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 90, bottom: 28, width: 90, height: 28, toJSON: () => ({}),
    });
    fireEvent.pointerDown(slider, { clientX: 45, pointerId: 1 });
    fireEvent.pointerUp(slider, { clientX: 45, pointerId: 1 });
    expect(onIntensityChange).toHaveBeenCalledWith("medium");
  });

  it("drags the chapter review window and snaps on release", () => {
    const onIntensityChange = vi.fn();
    render(
      <AppFloatingComposer
        ready
        intensity="low"
        onIntensityChange={onIntensityChange}
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    const slider = screen.getByRole("slider", { name: "快捷评审强度" });
    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 90, bottom: 28, width: 90, height: 28, toJSON: () => ({}),
    });
    fireEvent.pointerDown(slider, { clientX: 4, pointerId: 1 });
    fireEvent.pointerMove(slider, { clientX: 90, pointerId: 1 });
    expect(slider.querySelector("[data-intensity-window]").style.transform).toBe("translateX(200%)");
    fireEvent.pointerUp(slider, { clientX: 90, pointerId: 1 });
    expect(onIntensityChange).toHaveBeenCalledWith("high");
  });

  it("keeps the current intensity visible but locked while streaming", () => {
    const onIntensityChange = vi.fn();
    render(
      <AppFloatingComposer
        ready
        running
        intensity="high"
        streamLine="正在写第三段"
        onIntensityChange={onIntensityChange}
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onStop={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    const slider = screen.getByRole("slider", { name: "快捷评审强度" });
    expect(slider.getAttribute("aria-valuetext")).toBe("high");
    expect(slider.getAttribute("aria-disabled")).toBe("true");
    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 90, bottom: 28, width: 90, height: 28, toJSON: () => ({}),
    });
    fireEvent.pointerDown(slider, { clientX: 4, pointerId: 1 });
    fireEvent.pointerUp(slider, { clientX: 4, pointerId: 1 });
    expect(onIntensityChange).not.toHaveBeenCalled();
  });

  it("stays above the node detail overlay", () => {
    render(
      <AppFloatingComposer
        ready
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    expect(screen.getByTestId("app-floating-composer").className).toContain("z-[60]");
  });

  it("lifts above the on-screen keyboard", async () => {
    const visualViewport = {
      height: 500,
      offsetTop: 0,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
    Object.defineProperty(window, "visualViewport", { configurable: true, value: visualViewport });

    render(
      <AppFloatingComposer
        ready
        onNewSession={vi.fn()}
        onSend={vi.fn()}
        onExpandCharacters={vi.fn()}
        onExpandAgent={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("app-floating-composer").style.bottom).toBe("312px");
    });
    await act(async () => {
      Object.defineProperty(window, "innerHeight", { configurable: true, value: 500 });
      visualViewport.height = 500;
      visualViewport.addEventListener.mock.calls.forEach(([eventName, listener]) => {
        if (eventName === "resize") listener();
      });
    });
    expect(screen.getByTestId("app-floating-composer").style.bottom).toBe("312px");

    await act(async () => {
      Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
      visualViewport.height = 800;
      visualViewport.addEventListener.mock.calls.forEach(([eventName, listener]) => {
        if (eventName === "resize") listener();
      });
    });
    expect(screen.getByTestId("app-floating-composer").style.bottom).toBe("12px");
  });
});
