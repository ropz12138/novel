import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkbenchSidebar } from "./WorkbenchSidebar";

const listeners = new Set();
let mobile = false;

function installPointerEvent() {
  class PointerEventPolyfill extends window.MouseEvent {
    constructor(type, init = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
      this.pointerType = init.pointerType ?? "mouse";
    }
  }
  window.PointerEvent = PointerEventPolyfill;
}

function installMatchMedia() {
  mobile = false;
  listeners.clear();
  window.matchMedia = (query) => ({
    media: query,
    get matches() {
      return mobile;
    },
    addEventListener(type, listener) {
      if (type === "change") listeners.add(listener);
    },
    removeEventListener(type, listener) {
      if (type === "change") listeners.delete(listener);
    },
  });
}

function setMobile(next) {
  mobile = next;
  act(() => {
    listeners.forEach((listener) => listener());
  });
}

function renderSidebar(props = {}) {
  const onCollapsedChange = vi.fn();
  const onWidthChange = vi.fn();
  const view = render(
    <WorkbenchSidebar
      side="left"
      title="大纲"
      icon={<span data-testid="sidebar-icon">纲</span>}
      collapsed={false}
      onCollapsedChange={onCollapsedChange}
      width={320}
      onWidthChange={onWidthChange}
      headerExtra={<button type="button">附加</button>}
      {...props}
    >
      <p>栏内正文</p>
    </WorkbenchSidebar>,
  );
  return { ...view, onCollapsedChange, onWidthChange };
}

function Harness({ side = "left", initialWidth = 320, initialCollapsed = false }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [width, setWidth] = useState(initialWidth);
  return (
    <WorkbenchSidebar
      side={side}
      title={side === "left" ? "大纲" : "审查"}
      collapsed={collapsed}
      onCollapsedChange={setCollapsed}
      width={width}
      onWidthChange={setWidth}
    >
      <p>栏内正文</p>
    </WorkbenchSidebar>
  );
}

describe("WorkbenchSidebar", () => {
  beforeEach(() => {
    installMatchMedia();
    installPointerEvent();
  });

  afterEach(() => {
    listeners.clear();
  });

  it("在桌面展开时渲染标题、可选图标、附加区、正文和宽度", () => {
    const { container } = renderSidebar({ className: "custom-side" });
    const root = container.querySelector(".workbench-sidebar");

    expect(screen.getByText("大纲")).toBeDefined();
    expect(screen.getByTestId("sidebar-icon")).toBeDefined();
    expect(screen.getByRole("button", { name: "附加" })).toBeDefined();
    expect(screen.getByText("栏内正文")).toBeDefined();
    expect(screen.getByRole("button", { name: "收起大纲" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("separator", { name: "调整大纲宽度" }).getAttribute("aria-orientation")).toBe("vertical");
    expect(root.classList.contains("workbench-sidebar--left")).toBe(true);
    expect(root.classList.contains("custom-side")).toBe(true);
    expect(root.style.flexBasis).toBe("320px");
    expect(root.style.flexShrink).toBe("1");
    expect(root.style.minWidth).toBe("0");
  });

  it("收起后保留窄栏按钮，正文仍挂载且隐藏", () => {
    const opened = renderSidebar();
    fireEvent.click(screen.getByRole("button", { name: "收起大纲" }));
    expect(opened.onCollapsedChange).toHaveBeenCalledWith(true);
    opened.unmount();

    const { container } = renderSidebar({ collapsed: true, headerExtra: <button type="button">附加</button> });
    const root = container.querySelector(".workbench-sidebar");
    const body = container.querySelector(".workbench-sidebar__body");

    expect(screen.getByRole("button", { name: "展开大纲" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("separator", { name: "调整大纲宽度" })).toBeNull();
    expect(body.textContent).toContain("栏内正文");
    expect(body.hidden).toBe(true);
    expect(root.classList.contains("is-collapsed")).toBe(true);
    expect(root.style.flexBasis).toBe("40px");
    expect(root.style.width).toBe("40px");
  });

  it("左侧键盘向右加宽、向左变窄，并限制在200到520", () => {
    const { onWidthChange } = renderSidebar({ width: 200 });
    const separator = screen.getByRole("separator", { name: "调整大纲宽度" });
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(onWidthChange).toHaveBeenNthCalledWith(1, 200);
    expect(onWidthChange).toHaveBeenNthCalledWith(2, 220);

    onWidthChange.mockClear();
    const maxed = renderSidebar({ width: 520 });
    fireEvent.keyDown(screen.getAllByRole("separator", { name: "调整大纲宽度" })[1], { key: "ArrowRight" });
    fireEvent.keyDown(screen.getAllByRole("separator", { name: "调整大纲宽度" })[1], { key: "ArrowLeft" });
    expect(maxed.onWidthChange).toHaveBeenNthCalledWith(1, 520);
    expect(maxed.onWidthChange).toHaveBeenNthCalledWith(2, 500);
  });

  it("右侧键盘向左加宽、向右变窄，每次20像素", () => {
    const { onWidthChange } = renderSidebar({ side: "right", title: "审查", width: 300 });
    const separator = screen.getByRole("separator", { name: "调整审查宽度" });
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(onWidthChange).toHaveBeenNthCalledWith(1, 320);
    expect(onWidthChange).toHaveBeenNthCalledWith(2, 280);
  });

  it("用pointer捕获按对应侧拖宽，并在松开时释放", () => {
    render(<Harness side="left" initialWidth={300} />);
    const separator = screen.getByRole("separator", { name: "调整大纲宽度" });
    separator.setPointerCapture = vi.fn();
    separator.releasePointerCapture = vi.fn();

    fireEvent.pointerDown(separator, { button: 0, pointerId: 7, clientX: 300 });
    expect(separator.setPointerCapture).toHaveBeenCalledWith(7);
    fireEvent.pointerMove(separator, { pointerId: 7, clientX: 345 });
    expect(separator.parentElement.style.flexBasis).toBe("345px");
    fireEvent.pointerUp(separator, { pointerId: 7 });
    expect(separator.releasePointerCapture).toHaveBeenCalledWith(7);

    fireEvent.pointerDown(separator, { button: 2, pointerId: 8, clientX: 345 });
    fireEvent.pointerMove(separator, { pointerId: 8, clientX: 400 });
    expect(separator.parentElement.style.flexBasis).toBe("345px");
  });

  it("右侧向右拖动会变窄", () => {
    render(<Harness side="right" initialWidth={400} />);
    const separator = screen.getByRole("separator", { name: "调整审查宽度" });
    separator.setPointerCapture = vi.fn();
    separator.releasePointerCapture = vi.fn();
    fireEvent.pointerDown(separator, { button: 0, pointerId: 3, clientX: 500 });
    fireEvent.pointerMove(separator, { pointerId: 3, clientX: 560 });
    expect(separator.parentElement.style.flexBasis).toBe("340px");
    fireEvent.pointerUp(separator, { pointerId: 3, clientX: 560 });
    expect(separator.releasePointerCapture).toHaveBeenCalledWith(3);
  });

  it("拖动未结束就卸载时释放pointer捕获", () => {
    const { unmount } = render(<Harness side="left" initialWidth={280} />);
    const separator = screen.getByRole("separator", { name: "调整大纲宽度" });
    const release = vi.fn();
    separator.setPointerCapture = vi.fn();
    separator.releasePointerCapture = release;
    fireEvent.pointerDown(separator, { button: 0, pointerId: 4, clientX: 100 });
    unmount();
    expect(release).toHaveBeenCalledWith(4);
  });

  it("移动端忽略收起和宽度，隐藏收起与拖动控件并铺满", () => {
    setMobile(true);
    const { container } = renderSidebar({ collapsed: true, width: 480 });
    const root = container.querySelector(".workbench-sidebar");
    const body = container.querySelector(".workbench-sidebar__body");

    expect(screen.queryByRole("button", { name: "展开大纲" })).toBeNull();
    expect(screen.queryByRole("button", { name: "收起大纲" })).toBeNull();
    expect(screen.queryByRole("separator")).toBeNull();
    expect(body.hidden).toBe(false);
    expect(screen.getByText("栏内正文")).toBeDefined();
    expect(root.classList.contains("is-mobile")).toBe(true);
    expect(root.classList.contains("is-collapsed")).toBe(false);
    expect(root.style.width).toBe("100%");
    expect(root.style.flexBasis).toBe("100%");
    expect(root.style.minWidth).toBe("0");
  });

  it("视口越过800像素后恢复桌面收起状态", () => {
    setMobile(true);
    const { container } = renderSidebar({ collapsed: true, width: 360 });
    expect(container.querySelector(".workbench-sidebar__body").hidden).toBe(false);

    setMobile(false);
    const root = container.querySelector(".workbench-sidebar");
    expect(screen.getByRole("button", { name: "展开大纲" })).toBeDefined();
    expect(container.querySelector(".workbench-sidebar__body").hidden).toBe(true);
    expect(root.style.flexBasis).toBe("40px");
  });

  it("传入越界宽度时按200到520显示", () => {
    const { container, rerender } = renderSidebar({ width: 80 });
    expect(container.querySelector(".workbench-sidebar").style.flexBasis).toBe("200px");
    rerender(
      <WorkbenchSidebar
        side="left"
        title="大纲"
        collapsed={false}
        onCollapsedChange={() => {}}
        width={900}
        onWidthChange={() => {}}
      >
        <p>栏内正文</p>
      </WorkbenchSidebar>,
    );
    expect(container.querySelector(".workbench-sidebar").style.flexBasis).toBe("520px");
  });
});
