import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const apiMocks = vi.hoisted(() => ({
  fetchWorks: vi.fn(),
  createWork: vi.fn(),
  deleteWork: vi.fn(),
  fetchContentDiffs: vi.fn(),
  fetchNotesDiffs: vi.fn(),
}));

const agentChatRefMocks = vi.hoisted(() => ({
  send: vi.fn(),
  newSession: vi.fn(),
  selectSession: vi.fn(),
  setIntensity: vi.fn(),
  refresh: vi.fn(),
}));

const insertPillMock = vi.hoisted(() => vi.fn());

const canvasRefMocks = vi.hoisted(() => ({
  closeNodeDetail: vi.fn(() => false),
  openNodeDetail: vi.fn(),
  refresh: vi.fn(),
}));

const backNavigationMocks = vi.hoisted(() => ({
  listener: null,
  subscriptions: 0,
  resumeListener: null,
  resumeSubscriptions: 0,
  exitNativeApp: vi.fn(),
}));

vi.mock("../lib/appBackNavigation", () => ({
  subscribeAppBack: vi.fn(async (listener) => {
    backNavigationMocks.listener = listener;
    backNavigationMocks.subscriptions += 1;
    return vi.fn();
  }),
  subscribeAppResume: vi.fn(async (listener) => {
    backNavigationMocks.resumeListener = listener;
    backNavigationMocks.resumeSubscriptions += 1;
    return vi.fn();
  }),
  exitNativeApp: backNavigationMocks.exitNativeApp,
}));

vi.mock("../lib/canvasApi", () => ({
  fetchWorks: apiMocks.fetchWorks,
  createWork: apiMocks.createWork,
  deleteWork: apiMocks.deleteWork,
  fetchContentDiffs: apiMocks.fetchContentDiffs,
  fetchNotesDiffs: apiMocks.fetchNotesDiffs,
}));

vi.mock("../components/Canvas", () => ({
  default: forwardRef(function CanvasMock({ workId, nodeContentDiffs, appMode, charactersPanelOpen, onAddContext, onNodeEditingChange }, _ref) {
    useImperativeHandle(_ref, () => canvasRefMocks);
    return (
      <div data-testid="canvas-mock" data-work-id={workId}
        data-diff-count={Object.keys(nodeContentDiffs).length} data-app-mode={String(appMode)}
        data-characters-open={String(charactersPanelOpen)}>
        <button type="button" onClick={() => onAddContext?.({ id: "chapter-1", type: "chapter", label: "第一章" })}>
          引用此节点
        </button>
        <button type="button" onClick={() => onAddContext?.({ id: "chapter-1", type: "chapter", label: "第一章" }, "雨夜来客")}>
          引用此段
        </button>
        <button type="button" onClick={() => onNodeEditingChange?.(true)}>进入节点编辑</button>
        <button type="button" onClick={() => onNodeEditingChange?.(false)}>退出节点编辑</button>
      </div>
    );
  }),
}));

vi.mock("../components/AgentChat", () => ({
  default: forwardRef(function AgentChatMock({ workId, onNodeContentDiff, onOpenNodeDetail, onCollapse, onStateChange, insertPillRef, draft, onDraftChange }, ref) {
    const [sessionWorkId] = useState(workId);
    useImperativeHandle(ref, () => agentChatRefMocks);
    useEffect(() => {
      if (insertPillRef) insertPillRef.current = insertPillMock;
      return () => {
        if (insertPillRef) insertPillRef.current = null;
      };
    }, [insertPillRef]);
    useEffect(() => {
      onStateChange?.({
        ready: true,
        running: false,
        streamLine: "",
        sessions: [{ id: "s1", title: "上一轮对话" }],
        sessionId: "s1",
        chapterReviewIntensity: "low",
      });
    }, [onStateChange]);
    return <div data-testid="agent-chat-mock" data-session-work-id={sessionWorkId}>
      <button aria-label="收起Agent侧边栏" onClick={onCollapse}>收起Agent侧边栏</button>
      <textarea
        aria-label="创作指令"
        value={draft}
        onChange={(event) => onDraftChange?.(event.target.value)}
      />
      <button type="button" onClick={() => onOpenNodeDetail?.("chapter-1")}>打开diff节点</button>
      <button onClick={() => onNodeContentDiff?.("chapter-live", {
        grouping: "agent_replacements",
        original_content: "旧正文", current_content: "新正文",
        hunks: [{ type: "replace", paragraph_index: 1, start_offset: 0, old_text: "旧正文", new_text: "新正文" }],
      })}>模拟实时正文修改</button>
    </div>;
  }),
}));

vi.mock("../components/ModelConfigDialog", () => ({
  default: () => null,
}));

vi.mock("../components/AppUpdateButton", () => ({
  default: () => <button type="button">检查更新</button>,
}));

import { CanvasPage } from "./CanvasPage";

describe("CanvasPage delete work", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("PointerEvent", MouseEvent);
    window.localStorage.clear();
    window.localStorage.setItem("novel_role", "admin");
    vi.stubGlobal("confirm", vi.fn(() => true));
    backNavigationMocks.listener = null;
    backNavigationMocks.subscriptions = 0;
    backNavigationMocks.resumeListener = null;
    backNavigationMocks.resumeSubscriptions = 0;
    canvasRefMocks.closeNodeDetail.mockReturnValue(false);
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1280,
    });
    apiMocks.fetchWorks.mockResolvedValue({
      works: [
        { id: "w1", title: "作品一", created_at: "2026-01-01T00:00:00Z" },
        { id: "w2", title: "作品二", created_at: "2026-01-02T00:00:00Z" },
      ],
    });
    apiMocks.deleteWork.mockResolvedValue(undefined);
    apiMocks.fetchContentDiffs.mockResolvedValue([]);
    apiMocks.fetchNotesDiffs.mockResolvedValue([]);
  });

  it("shows delete button in work selector and calls deleteWork", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByText("作品一");

    fireEvent.click(screen.getByText("作品:"));

    const deleteButtons = await screen.findAllByTitle("删除作品");
    expect(deleteButtons.length).toBe(2);

    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(apiMocks.deleteWork).toHaveBeenCalledWith("w1");
    });
  });

  it("restores the last active work after a page refresh", async () => {
    window.localStorage.setItem("novel_canvas_last_active_work", "w2");

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    const canvas = await screen.findByTestId("canvas-mock");
    expect(canvas.dataset.workId).toBe("w2");
    expect(screen.getByText("作品二")).toBeDefined();
  });

  it("switches the chat session scope with the selected work", async () => {
    render(<MemoryRouter><CanvasPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("agent-chat-mock").dataset.sessionWorkId).toBe("w1"));
    fireEvent.click(screen.getByText("作品:"));
    fireEvent.click(screen.getByText("作品二"));
    await waitFor(() => expect(screen.getByTestId("canvas-mock").dataset.workId).toBe("w2"));
    expect(screen.getByTestId("agent-chat-mock").dataset.sessionWorkId).toBe("w2");
  });

  it("restores pending agent body diffs from the server", async () => {
    apiMocks.fetchContentDiffs.mockResolvedValue([{
      node_id: "chapter-1", original_content: "旧正文", current_content: "新正文",
      grouping: "agent_replacements",
      hunks: [{ type: "replace", start_offset: 0, old_text: "旧正文", new_text: "新正文" }],
    }]);
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("canvas-mock").dataset.diffCount).toBe("1"));
  });

  it("shows an agent body diff as soon as the live event arrives", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );
    await screen.findByTestId("canvas-mock");
    fireEvent.click(screen.getByRole("button", { name: "模拟实时正文修改" }));
    await waitFor(() => expect(screen.getByTestId("canvas-mock").dataset.diffCount).toBe("1"));
  });

  it("lets the user drag the chat panel wider", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByTestId("agent-chat-mock");

    const separator = screen.getByRole("separator", { name: "调整对话区域宽度" });
    const panel = separator.parentElement;
    const initialWidth = Number.parseInt(panel.style.width, 10);
    expect(initialWidth).toBeGreaterThanOrEqual(340);

    fireEvent.mouseDown(separator, { button: 0, clientX: 900 });
    fireEvent.mouseMove(window, { clientX: 780 });
    fireEvent.mouseUp(window);

    const expectedWidth = initialWidth + 120;
    await waitFor(() => {
      expect(panel.style.width).toBe(`${expectedWidth}px`);
      expect(window.localStorage.getItem("novel_canvas_chat_width")).toBe(String(expectedWidth));
    });
  });

  it("expands and collapses Agent from controls in the sidebar", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByTestId("agent-chat-mock");
    expect(screen.queryByText("隐藏Agent")).toBeNull();
    expect(screen.queryByText("显示Agent")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "收起Agent侧边栏" }));
    expect(screen.queryByTestId("agent-chat-mock")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "展开Agent侧边栏" }));
    expect(await screen.findByTestId("agent-chat-mock")).toBeDefined();
  });

  it("opens a diff node detail from the Web Agent conversation", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByTestId("agent-chat-mock");
    fireEvent.click(screen.getByRole("button", { name: "打开diff节点" }));
    expect(canvasRefMocks.openNodeDetail).toHaveBeenCalledWith("chapter-1");
  });

  it("uses the compact initial layout and account update entry in App mode", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    const canvas = await screen.findByTestId("canvas-mock");
    expect(canvas.dataset.appMode).toBe("true");
    expect(screen.queryByText("文灵")).toBeNull();
    expect(screen.getByTestId("agent-chat-mock")).toBeDefined();
    expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("true");
    expect(screen.getByRole("button", { name: "展开Agent侧边栏" })).toBeDefined();
    const characters = screen.getByRole("button", { name: "展开角色与设定" });
    expect(characters.className).toContain("right-3");
    expect(characters.className).not.toContain("left-3");
    expect(screen.getByTestId("app-floating-composer").contains(characters)).toBe(false);
    expect(canvas.dataset.charactersOpen).toBe("false");
    fireEvent.click(characters);
    expect(screen.getByTestId("canvas-mock").dataset.charactersOpen).toBe("true");
    expect(screen.queryByRole("button", { name: "展开角色与设定" })).toBeNull();
    expect(screen.queryByRole("button", { name: "检查更新" })).toBeNull();

    fireEvent.click(screen.getByTitle("账户"));
    expect(screen.getByRole("button", { name: "检查更新" })).toBeDefined();
    expect(screen.getByText("模型配置")).toBeDefined();
    expect(screen.getByText("退出登录")).toBeDefined();
  });

  it("hides the floating composer while the Agent sidebar is expanded in App mode", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    expect(screen.getByRole("textbox", { name: "快捷创作指令" })).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "展开Agent侧边栏" }));

    expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("false");
    expect(screen.getByTestId("agent-panel").className).toContain("absolute");
    expect(screen.getByTestId("agent-panel").className).toContain("inset-0");
    expect(screen.getByTestId("agent-panel").className).toContain("z-[70]");
    expect(screen.queryByRole("separator", { name: "调整对话区域宽度" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "快捷创作指令" })).toBeNull();
  });

  it("hides the floating composer while a node is being edited in App mode", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    expect(screen.getByRole("textbox", { name: "快捷创作指令" })).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "进入节点编辑" }));
    expect(screen.queryByRole("textbox", { name: "快捷创作指令" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "退出节点编辑" }));
    expect(screen.getByRole("textbox", { name: "快捷创作指令" })).toBeDefined();
  });

  it("shares one draft between the App floating composer and Agent conversation", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    fireEvent.change(screen.getByRole("textbox", { name: "快捷创作指令" }), {
      target: { value: "强化这一段的冲突" },
    });

    fireEvent.click(screen.getByRole("button", { name: "会话列表" }));
    fireEvent.click(screen.getByRole("button", { name: "新对话" }));
    expect(screen.getByRole("textbox", { name: "快捷创作指令" }).value)
      .toBe("强化这一段的冲突");

    fireEvent.click(screen.getByRole("button", { name: "展开Agent侧边栏" }));
    const conversationInput = screen.getByRole("textbox", { name: "创作指令" });
    expect(conversationInput.value).toBe("强化这一段的冲突");

    fireEvent.change(conversationInput, { target: { value: "改为强化人物动机" } });
    fireEvent.click(screen.getByRole("button", { name: "收起Agent侧边栏" }));
    expect(screen.getByRole("textbox", { name: "快捷创作指令" }).value)
      .toBe("改为强化人物动机");

    fireEvent.click(screen.getByRole("button", { name: "发送快捷指令" }));
    expect(agentChatRefMocks.send).toHaveBeenCalledWith("改为强化人物动机");
    expect(screen.getByRole("textbox", { name: "快捷创作指令" }).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "展开Agent侧边栏" }));
    expect(screen.getByRole("textbox", { name: "创作指令" }).value).toBe("");
  });

  it("closes the right Agent sidebar before the Android back button exits the App", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    fireEvent.click(screen.getByRole("button", { name: "展开Agent侧边栏" }));
    expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("false");

    await waitFor(() => expect(backNavigationMocks.subscriptions).toBeGreaterThanOrEqual(2));

    backNavigationMocks.listener();
    await waitFor(() => {
      expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("true");
    });
    expect(backNavigationMocks.exitNativeApp).not.toHaveBeenCalled();
  });

  it("closes node details before the Android back button exits the App", async () => {
    canvasRefMocks.closeNodeDetail.mockReturnValue(true);
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    await waitFor(() => expect(backNavigationMocks.listener).not.toBeNull());

    backNavigationMocks.listener();

    expect(canvasRefMocks.closeNodeDetail).toHaveBeenCalledOnce();
    expect(backNavigationMocks.exitNativeApp).not.toHaveBeenCalled();
  });

  it("closes the App conversation before an underlying node detail", async () => {
    canvasRefMocks.closeNodeDetail.mockReturnValue(true);
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    fireEvent.click(screen.getByRole("button", { name: "展开Agent侧边栏" }));
    await waitFor(() => expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("false"));

    backNavigationMocks.listener();

    await waitFor(() => expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("true"));
    expect(canvasRefMocks.closeNodeDetail).not.toHaveBeenCalled();
    expect(backNavigationMocks.exitNativeApp).not.toHaveBeenCalled();
  });

  it("refreshes App data when Android returns to the foreground", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );
    await screen.findByTestId("canvas-mock");
    await waitFor(() => expect(backNavigationMocks.resumeListener).not.toBeNull());
    vi.clearAllMocks();

    backNavigationMocks.resumeListener();

    await waitFor(() => {
      expect(canvasRefMocks.refresh).toHaveBeenCalledOnce();
      expect(agentChatRefMocks.refresh).toHaveBeenCalledOnce();
      expect(apiMocks.fetchWorks).toHaveBeenCalledOnce();
      expect(apiMocks.fetchContentDiffs).toHaveBeenCalledOnce();
    });
  });

  it("lets App mode pick a session from the floating composer", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    fireEvent.click(screen.getByRole("button", { name: "会话列表" }));
    fireEvent.click(screen.getByRole("button", { name: "上一轮对话" }));
    expect(agentChatRefMocks.selectSession).toHaveBeenCalledWith({ id: "s1", title: "上一轮对话" });

    fireEvent.click(screen.getByRole("button", { name: "会话列表" }));
    fireEvent.click(screen.getByRole("button", { name: "新对话" }));
    expect(agentChatRefMocks.newSession).toHaveBeenCalledOnce();

    const slider = screen.getByRole("slider", { name: "快捷评审强度" });
    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 90, bottom: 28, width: 90, height: 28, toJSON: () => ({}),
    });
    fireEvent.pointerDown(slider, { clientX: 45, pointerId: 1 });
    fireEvent.pointerUp(slider, { clientX: 45, pointerId: 1 });
    expect(agentChatRefMocks.setIntensity).toHaveBeenCalledWith("medium");
  });

  it("offsets the App header below the system status bar", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    expect(screen.getByTestId("canvas-page-header").className).toContain("safe-area-inset-top");
  });

  it("closes work and account menus when clicking outside", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    fireEvent.click(screen.getByText("作品:"));
    expect(screen.getByText("创建新作品")).toBeDefined();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByText("创建新作品")).toBeNull();

    fireEvent.click(screen.getByTitle("账户"));
    expect(screen.getByText("模型配置")).toBeDefined();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByText("模型配置")).toBeNull();
  });

  it("expands Agent and inserts a node quote from the canvas", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage appMode />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "引用此节点" }));

    expect(screen.getByTestId("agent-panel").getAttribute("aria-hidden")).toBe("false");
    expect(insertPillMock).toHaveBeenCalledWith("chapter-1", "chapter", "第一章", undefined);
  });

  it("expands Agent and inserts a paragraph quote from the canvas", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByTestId("canvas-mock");
    fireEvent.click(screen.getByRole("button", { name: "收起Agent侧边栏" }));
    expect(screen.queryByTestId("agent-chat-mock")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "引用此段" }));

    expect(await screen.findByTestId("agent-chat-mock")).toBeDefined();
    await waitFor(() => {
      expect(insertPillMock).toHaveBeenCalledWith("chapter-1", "chapter", "第一章", "雨夜来客");
    });
  });

  it("opens token usage from the web header", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/" element={<CanvasPage />} />
          <Route path="/token-usage" element={<div>用量页</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText("作品一");
    fireEvent.click(screen.getByRole("button", { name: "Token 用量" }));
    expect(await screen.findByText("用量页")).toBeTruthy();
  });

  it("hides model configuration and token usage from user accounts", async () => {
    window.localStorage.setItem("novel_role", "user");
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );
    await screen.findByText("作品一");
    expect(screen.queryByRole("button", { name: "Token 用量" })).toBeNull();
    fireEvent.click(screen.getByTitle("账户"));
    expect(screen.queryByText("模型配置")).toBeNull();
  });

  it("opens token usage from the app header", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/" element={<CanvasPage appMode />} />
          <Route path="/token-usage" element={<div>用量页</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByTestId("canvas-mock");
    expect(screen.queryByText("Token 用量")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Token 用量" }));
    expect(await screen.findByText("用量页")).toBeTruthy();
  });
});
