import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchPage } from "./ResearchPage";

const mocks = vi.hoisted(() => ({
  uploadWork: vi.fn(), listWorks: vi.fn(), listSessions: vi.fn(),
  createSession: vi.fn(), getSession: vi.fn(), sendMessage: vi.fn(), getLibrary: vi.fn(),
  listVersions: vi.fn(), downloadUrl: vi.fn(),
  listChapters: vi.fn(), getChapter: vi.fn(),
}));

vi.mock("../lib/researchApi", () => ({
  researchApi: {
    ...mocks,
  },
}));

describe("ResearchPage conversations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listWorks.mockResolvedValue({ works: [{ id: "work-1", original_filename: "novel.txt" }] });
    mocks.listSessions.mockResolvedValue({ sessions: [{ id: "session-1", title: "新对话" }] });
    mocks.getSession.mockResolvedValue({ id: "session-1", title: "新对话", messages: [] });
    mocks.createSession.mockResolvedValue({ id: "session-2", title: "新对话" });
    mocks.uploadWork.mockResolvedValue({ job_id: "work-2" });
    mocks.sendMessage.mockResolvedValue({ user_message: {}, assistant_message: {} });
    mocks.getLibrary.mockResolvedValue({ works: [{
      id: "work-1", original_filename: "novel.txt", artifacts: [{
        id: "artifact-1", artifact_type: "technique_card",
        title: "C01-开篇钩子", content: "技法卡正文",
      }],
    }, { id: "work-2", original_filename: "another.txt", artifacts: [] }] });
    mocks.listVersions.mockResolvedValue({ versions: [{
      id: "version-1", version_number: 0, kind: "raw", encoding: "utf-8", active: true,
    }, {
      id: "clean-v1", version_number: 1, kind: "cleaned", encoding: "utf-8",
      active: false, has_index: true,
    }] });
    mocks.listChapters.mockResolvedValue({ chapters: [{
      section_index: 0, number: 1, title: "开始", heading: "第一章 开始",
    }] });
    mocks.getChapter.mockResolvedValue({
      section_index: 0, number: 1, title: "开始", heading: "第一章 开始",
      content: "第一章 开始\n章节正文",
    });
    mocks.downloadUrl.mockReturnValue("/api/research/download");
  });

  it("uploads a work without starting a conversation", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ResearchPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.listWorks).toHaveBeenCalled());
    const target = screen.getByText("作品库");
    const file = new File(["第一章\n正文"], "novel.txt", {
      type: "text/plain",
    });

    fireEvent.dragEnter(target, {
      dataTransfer: { types: ["Files"], files: [file] },
    });
    expect(screen.getByText("松开鼠标，上传作品")).toBeTruthy();

    fireEvent.drop(target, {
      dataTransfer: { types: ["Files"], files: [file] },
    });

    await waitFor(() => expect(mocks.uploadWork).toHaveBeenCalledWith(file));
  });

  it("creates and switches independent conversations", async () => {
    render(<MemoryRouter><ResearchPage /></MemoryRouter>);
    await waitFor(() => expect(mocks.getSession).toHaveBeenCalledWith("session-1"));
    fireEvent.click(screen.getByRole("button", { name: "新建对话" }));
    await waitFor(() => expect(mocks.createSession).toHaveBeenCalled());
    await waitFor(() => expect(mocks.getSession).toHaveBeenCalledWith("session-2"));
  });

  it("sends the selected work as a message reference", async () => {
    render(<MemoryRouter><ResearchPage /></MemoryRouter>);
    const workLabels = await screen.findAllByText("novel.txt");
    fireEvent.click(workLabels[0]);
    fireEvent.change(screen.getByPlaceholderText("输入研究问题……"), { target: { value: "分析开篇" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledWith("session-1", "分析开篇", "work-1", null));
  });

  it("shows technique cards for the selected work", async () => {
    render(<MemoryRouter><ResearchPage /></MemoryRouter>);
    await waitFor(() => expect(mocks.getLibrary).toHaveBeenCalled());
    expect(await screen.findByText("another.txt")).toBeTruthy();
    expect(await screen.findByText("C01-开篇钩子")).toBeTruthy();
    fireEvent.click(screen.getByText("C01-开篇钩子"));
    expect(await screen.findByText("技法卡正文")).toBeTruthy();
  });

  it("shows original and cleaned text versions", async () => {
    render(<MemoryRouter><ResearchPage /></MemoryRouter>);
    await waitFor(() => expect(mocks.listVersions).toHaveBeenCalledWith("work-1"));
    expect(await screen.findByText("原始版")).toBeTruthy();
  });

  it("reads and references one cleaned-text chapter", async () => {
    render(<MemoryRouter><ResearchPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "章节阅读" }));
    const chapter = await screen.findByText("第一章 开始");
    fireEvent.click(chapter);
    expect(await screen.findByText(/章节正文/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "引用本章" }));
    fireEvent.change(screen.getByPlaceholderText("输入研究问题……"), { target: { value: "分析本章" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledWith(
      "session-1", "分析本章", "work-1",
      { versionId: "clean-v1", sectionIndex: 0 },
    ));
  });
});
