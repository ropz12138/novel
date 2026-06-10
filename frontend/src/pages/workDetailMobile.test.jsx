import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  MobileChapterStrip,
  MobileWorkNav,
  characterCardsGridClassName,
  resolveDefaultChapterNum,
  resolveMobilePanelFromRoute,
  shouldShowWorkPanel,
  shouldSyncOutlineNodeSelection,
} from "./workDetailMobile";

describe("resolveMobilePanelFromRoute", () => {
  it("returns chat when chat is open", () => {
    expect(resolveMobilePanelFromRoute("outline", true)).toBe("chat");
    expect(resolveMobilePanelFromRoute("chapter", true)).toBe("chat");
  });

  it("returns outline or detail from main tab when chat is closed", () => {
    expect(resolveMobilePanelFromRoute("outline", false)).toBe("outline");
    expect(resolveMobilePanelFromRoute("chapter", false)).toBe("detail");
  });
});

describe("shouldShowWorkPanel", () => {
  it("uses mainTab on desktop and mobilePanel on mobile", () => {
    expect(shouldShowWorkPanel(false, "detail", "outline", "outline")).toBe(true);
    expect(shouldShowWorkPanel(false, "detail", "outline", "detail")).toBe(false);
    expect(shouldShowWorkPanel(false, "chat", "chapter", "chat")).toBe(false);
    expect(shouldShowWorkPanel(true, "chat", "chapter", "chat")).toBe(true);
    expect(shouldShowWorkPanel(true, "chat", "chapter", "detail")).toBe(false);
  });
});

describe("MobileWorkNav", () => {
  it("renders three tabs and invokes handlers", () => {
    const onOutline = vi.fn();
    const onDetail = vi.fn();
    const onChat = vi.fn();

    render(
      <MobileWorkNav panel="detail" onOutline={onOutline} onDetail={onDetail} onChat={onChat} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /大纲/ }));
    fireEvent.click(screen.getByRole("button", { name: /正文/ }));
    fireEvent.click(screen.getByRole("button", { name: /对话/ }));

    expect(onOutline).toHaveBeenCalledTimes(1);
    expect(onDetail).toHaveBeenCalledTimes(1);
    expect(onChat).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /正文/ }).getAttribute("aria-current")).toBe("page");
  });
});

describe("shouldSyncOutlineNodeSelection", () => {
  it("disables cross-panel node sync on mobile", () => {
    expect(shouldSyncOutlineNodeSelection(true)).toBe(false);
    expect(shouldSyncOutlineNodeSelection(false)).toBe(true);
  });
});

describe("characterCardsGridClassName", () => {
  it("uses single full-width column on mobile", () => {
    expect(characterCardsGridClassName(true)).toContain("grid-cols-1");
    expect(characterCardsGridClassName(true)).toContain("min-w-0");
  });

  it("uses multi-column grid on desktop", () => {
    expect(characterCardsGridClassName(false)).toContain("md:grid-cols-2");
    expect(characterCardsGridClassName(false)).toContain("xl:grid-cols-3");
  });
});

describe("resolveDefaultChapterNum", () => {
  it("selects the latest filled chapter by chapter number", () => {
    expect(resolveDefaultChapterNum([1, 4, 2], [1, 2, 3, 4, 5])).toBe(4);
  });

  it("falls back to the latest outline chapter when no filled chapters exist", () => {
    expect(resolveDefaultChapterNum([], [1, 3, 2])).toBe(3);
  });

  it("returns null when no chapters are available", () => {
    expect(resolveDefaultChapterNum([], [])).toBeNull();
  });
});

describe("MobileChapterStrip", () => {
  it("renders chapters and selects one", () => {
    const onSelect = vi.fn();
    const chapters = [
      { chapter_number: 1, title: "开端" },
      { chapter_number: 2, title: "" },
    ];

    render(<MobileChapterStrip chapters={chapters} activeNum={1} onSelect={onSelect} />);

    expect(screen.getByRole("tab", { name: /第1章 · 开端/ }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: /第2章/ }));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it("renders nothing when chapters are empty", () => {
    const { container } = render(
      <MobileChapterStrip chapters={[]} activeNum={null} onSelect={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
