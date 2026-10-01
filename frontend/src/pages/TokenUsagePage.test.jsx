import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TokenUsagePage } from "./TokenUsagePage";

const mocks = vi.hoisted(() => ({
  getUsage: vi.fn(),
}));

const backNavigationMocks = vi.hoisted(() => ({
  listener: null,
  subscriptions: 0,
}));

vi.mock("../lib/appBackNavigation", () => ({
  subscribeAppBack: vi.fn(async (listener) => {
    backNavigationMocks.listener = listener;
    backNavigationMocks.subscriptions += 1;
    return vi.fn();
  }),
}));

vi.mock("../lib/tokenUsageApi", () => ({
  tokenUsageApi: {
    getUsage: mocks.getUsage,
  },
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage(appMode = false) {
  return render(
    <MemoryRouter
      initialEntries={["/token-usage"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/token-usage" element={<TokenUsagePage appMode={appMode} />} />
        <Route path="/" element={<div>创作画布</div>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("TokenUsagePage", () => {
  beforeEach(() => {
    backNavigationMocks.listener = null;
    backNavigationMocks.subscriptions = 0;
    vi.clearAllMocks();
    mocks.getUsage.mockResolvedValue({
      works: [
        { id: "w1", title: "甲作品" },
        { id: "w2", title: "乙作品" },
      ],
      models: [
        { model: "glm-5.3-flash", cached_input_tokens: 4, uncached_input_tokens: 14, output_tokens: 10, cached_input_percent: 22.2, average_time_to_first_token_ms: 250, average_output_tokens_per_second: 20, latest_time_to_first_token_ms: 180, latest_output_tokens_per_second: 24.5 },
        { model: "mimo-v2.6-flash", cached_input_tokens: 0, uncached_input_tokens: 13, output_tokens: 18, cached_input_percent: 0, average_time_to_first_token_ms: 800, average_output_tokens_per_second: 45.25, latest_time_to_first_token_ms: 700, latest_output_tokens_per_second: 48 },
        { model: "deepseek-flash", cached_input_tokens: 2, uncached_input_tokens: 7, output_tokens: 1, cached_input_percent: 22.2, average_time_to_first_token_ms: null, average_output_tokens_per_second: null, latest_time_to_first_token_ms: null, latest_output_tokens_per_second: null },
      ],
      series: [
        { model: "glm-5.3-flash", points: [{ bucket: "2026-09-23", cached_input_tokens: 4, uncached_input_tokens: 14, output_tokens: 10 }] },
        { model: "mimo-v2.6-flash", points: [{ bucket: "2026-09-23", cached_input_tokens: 0, uncached_input_tokens: 13, output_tokens: 18 }] },
        { model: "deepseek-flash", points: [{ bucket: "2026-09-23", cached_input_tokens: 2, uncached_input_tokens: 7, output_tokens: 1 }] },
      ],
    });
  });

  it("lists cached input, uncached input, and output for each model on web", async () => {
    renderPage(false);
    expect(await screen.findAllByText("glm-5.3-flash")).toBeTruthy();
    expect(screen.getAllByText("mimo-v2.6-flash").length).toBeGreaterThan(0);
    expect(screen.getAllByText("deepseek-flash").length).toBeGreaterThan(0);
    expect(screen.getAllByText("缓存输入").length).toBeGreaterThan(0);
    expect(screen.getAllByText("未缓存输入").length).toBeGreaterThan(0);
    expect(screen.getAllByText("输出").length).toBeGreaterThan(0);
    expect(screen.getByText("14")).toBeTruthy();
    expect(screen.getByText("18")).toBeTruthy();
    expect(screen.getByText("平均端到端速度")).toBeTruthy();
    expect(screen.getByText("45.25 token/s")).toBeTruthy();
    expect(screen.getByText("最近首 Token")).toBeTruthy();
    expect(screen.getByText("180 ms")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("token-usage-app-header")).toBeNull();
  });

  it("uses the app header layout", async () => {
    renderPage(true);
    expect(await screen.findByTestId("token-usage-app-header")).toBeTruthy();
    expect(screen.getAllByText("deepseek-flash").length).toBeGreaterThan(0);
    expect(screen.getAllByText("平均端到端速度").length).toBeGreaterThan(0);
    expect(screen.getByText("24.50 token/s")).toBeTruthy();
  });

  it("shows the request error instead of empty totals", async () => {
    mocks.getUsage.mockRejectedValue(new Error("用量接口不可用"));
    renderPage(false);
    expect(await screen.findByText("用量接口不可用")).toBeTruthy();
    expect(screen.queryByText("glm-5.3-flash")).toBeNull();
  });

  it("draws one row per model with three token bars from the logs", async () => {
    renderPage(false);
    expect(await screen.findAllByRole("img", { name: /Token 用量$/ })).toHaveLength(3);
    expect(screen.getByTestId("token-usage-row-glm-5.3-flash")).toBeTruthy();
    expect(screen.getByTestId("token-usage-row-mimo-v2.6-flash")).toBeTruthy();
    expect(screen.getByTestId("token-usage-row-deepseek-flash")).toBeTruthy();
    const cached = screen.getByTestId("bar-glm-5.3-flash-2026-09-23-cached_input_tokens");
    const uncached = screen.getByTestId("bar-glm-5.3-flash-2026-09-23-uncached_input_tokens");
    const output = screen.getByTestId("bar-glm-5.3-flash-2026-09-23-output_tokens");
    expect(Number(uncached.getAttribute("height"))).toBeGreaterThan(Number(cached.getAttribute("height")));
    expect(Number(output.getAttribute("height"))).toBeGreaterThan(0);
    expect(screen.queryByTestId("bar-tip-glm-5.3-flash-2026-09-23-cached_input_tokens")).toBeNull();
    fireEvent.mouseEnter(cached);
    expect(screen.getByTestId("bar-tip-glm-5.3-flash-2026-09-23-cached_input_tokens").textContent).toBe("缓存输入 4");
    fireEvent.mouseLeave(cached);
    expect(screen.queryByTestId("bar-tip-glm-5.3-flash-2026-09-23-cached_input_tokens")).toBeNull();
    const empty = screen.getByTestId("bar-mimo-v2.6-flash-2026-09-23-cached_input_tokens");
    fireEvent.mouseEnter(empty);
    expect(screen.getByTestId("bar-tip-mimo-v2.6-flash-2026-09-23-cached_input_tokens").textContent).toBe("缓存输入 0");
    expect(screen.getAllByText("09-23").length).toBe(3);
    expect(screen.getAllByText("22.2%").length).toBeGreaterThan(0);
  });

  it("switches the x-axis between day and hour", async () => {
    mocks.getUsage.mockImplementation(async (workId, grain) => ({
      works: [],
      models: [
        { model: "glm-5.3-flash", cached_input_tokens: 4, uncached_input_tokens: 14, output_tokens: 10, cached_input_percent: 22.2 },
      ],
      series: [{
        model: "glm-5.3-flash",
        points: [grain === "hour"
          ? { bucket: "2026-09-23T10:00:00+08:00", cached_input_tokens: 4, uncached_input_tokens: 14, output_tokens: 10 }
          : { bucket: "2026-09-23", cached_input_tokens: 4, uncached_input_tokens: 14, output_tokens: 10 }],
      }],
    }));
    renderPage(false);
    expect(await screen.findByText("09-23")).toBeTruthy();
    expect(screen.getByRole("button", { name: "天" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "小时" }));
    expect(await screen.findByText("09-23 10:00")).toBeTruthy();
    expect(mocks.getUsage).toHaveBeenLastCalledWith(undefined, "hour");
    expect(screen.getByRole("button", { name: "小时" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("draws the same chart in the app layout", async () => {
    renderPage(true);
    expect(await screen.findAllByRole("img", { name: /Token 用量$/ })).toHaveLength(3);
    expect(screen.getAllByText("22.2%").length).toBeGreaterThan(0);
  });

  it("filters usage by work title", async () => {
    mocks.getUsage.mockImplementation(async (workId) => ({
      works: [
        { id: "w1", title: "甲作品" },
        { id: "w2", title: "乙作品" },
      ],
      models: workId === "w1"
        ? [{ model: "glm-5.3-flash", cached_input_tokens: 4, uncached_input_tokens: 14, output_tokens: 10, cached_input_percent: 22.2 }]
        : [{ model: "glm-5.3-flash", cached_input_tokens: 8, uncached_input_tokens: 2, output_tokens: 3, cached_input_percent: 80 }],
      series: [{
        model: "glm-5.3-flash",
        points: [{ bucket: "2026-09-23", cached_input_tokens: 1, uncached_input_tokens: 1, output_tokens: 1 }],
      }],
    }));
    renderPage(false);
    await screen.findByText("80.0%");
    fireEvent.change(screen.getByRole("combobox", { name: "作品" }), { target: { value: "w1" } });
    expect(await screen.findByText("22.2%")).toBeTruthy();
    expect(mocks.getUsage).toHaveBeenLastCalledWith("w1", "day");
  });

  it("returns to the canvas", async () => {
    renderPage(false);
    await screen.findAllByText("glm-5.3-flash");
    expect(screen.getByRole("link", { name: "返回创作画布" }).getAttribute("href")).toBe("/");
    fireEvent.click(screen.getByRole("link", { name: "返回创作画布" }));
    expect(await screen.findByText("创作画布")).toBeTruthy();
  });

  it("leaves the token page when the app system back button is pressed", async () => {
    renderPage(true);
    await screen.findByTestId("token-usage-app-header");
    await waitFor(() => expect(backNavigationMocks.subscriptions).toBe(1));
    backNavigationMocks.listener();
    expect(await screen.findByText("创作画布")).toBeTruthy();
    expect(screen.getByTestId("location").textContent).toBe("/");
  });
});
