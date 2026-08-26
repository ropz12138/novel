import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchPage } from "./ResearchPage";

const mocks = vi.hoisted(() => ({
  upload: vi.fn(),
  listJobs: vi.fn(),
  getJob: vi.fn(),
  getEvents: vi.fn(),
}));

vi.mock("../lib/researchApi", () => ({
  researchApi: {
    upload: mocks.upload,
    listJobs: mocks.listJobs,
    getJob: mocks.getJob,
    getEvents: mocks.getEvents,
    pause: vi.fn(),
    continue: vi.fn(),
    downloadUrl: vi.fn(),
  },
}));

describe("ResearchPage drag upload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listJobs.mockResolvedValue({ jobs: [] });
    mocks.getEvents.mockResolvedValue({ events: [] });
    mocks.upload.mockResolvedValue({ job_id: "job-1" });
    mocks.getJob.mockResolvedValue({
      id: "job-1",
      original_filename: "novel.txt",
      status: "running",
      stage: "检查文件",
      progress_current: 0,
      progress_total: 0,
      progress_unit: "步骤",
      progress_detail: "",
      versions: [],
      artifacts: [],
    });
  });

  it("uploads one dropped txt file and shows the drop overlay", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ResearchPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.listJobs).toHaveBeenCalled());
    const target = screen.getByText("小说研究 Agent");
    const file = new File(["第一章\n正文"], "novel.txt", {
      type: "text/plain",
    });

    fireEvent.dragEnter(target, {
      dataTransfer: { types: ["Files"], files: [file] },
    });
    expect(screen.getByText("松开鼠标，上传小说 TXT")).toBeTruthy();

    fireEvent.drop(target, {
      dataTransfer: { types: ["Files"], files: [file] },
    });

    await waitFor(() => expect(mocks.upload).toHaveBeenCalledWith(file));
  });

  it("polls only events after the latest received sequence", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const job = {
      id: "job-1",
      original_filename: "novel.txt",
      status: "running",
      stage: "阅读章节",
      progress_current: 1,
      progress_total: 10,
      progress_unit: "章",
      progress_detail: "正在阅读第一章",
      versions: [],
      artifacts: [],
    };
    mocks.listJobs.mockResolvedValue({ jobs: [job] });
    mocks.getJob.mockResolvedValue(job);
    mocks.getEvents.mockImplementation((_jobId, after) => Promise.resolve({
      events: after === 0
        ? [{
            id: "event-7",
            sequence: 7,
            event_type: "agent",
            content: "我正在检查章节结构。",
            meta_text: "{}",
            created_at: "2026-07-29T17:00:00+08:00",
          }]
        : [],
    }));

    try {
      render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <ResearchPage />
        </MemoryRouter>,
      );

      await waitFor(() => {
        expect(mocks.getEvents).toHaveBeenCalledWith("job-1", 0);
        expect(screen.getByText("我正在检查章节结构。")).toBeTruthy();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500);
      });

      await waitFor(() => {
        expect(
          mocks.getEvents.mock.calls.some(
            ([jobId, after]) => jobId === "job-1" && after === 7,
          ),
        ).toBe(true);
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
