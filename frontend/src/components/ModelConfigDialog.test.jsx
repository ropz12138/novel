import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

vi.mock("../lib/canvasApi", () => ({
  getModels: vi.fn(),
  getModelPref: vi.fn(),
  putModelPref: vi.fn(),
}));

import ModelConfigDialog from "./ModelConfigDialog";
import { getModels, getModelPref, putModelPref } from "../lib/canvasApi";

describe("ModelConfigDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getModels.mockResolvedValue({
      available_models: ["mimo-v2.5-pro", "deepseek-v4-flash"],
      default_primary: "mimo-v2.5-pro",
      default_fallback: "deepseek-v4-flash",
    });
    getModelPref.mockResolvedValue({ primary: null, fallback: null });
    putModelPref.mockResolvedValue({ primary: null, fallback: null });
  });

  it("renders nothing when closed", () => {
    const { container } = render(<ModelConfigDialog open={false} onClose={() => {}} />);
    expect(container.innerHTML).toBe("");
  });

  it("loads models and current pref when open", async () => {
    render(<ModelConfigDialog open={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("模型配置")).not.toBeNull();
    });
    expect(getModels).toHaveBeenCalledTimes(1);
    expect(getModelPref).toHaveBeenCalledTimes(1);
  });

  it("saves preference and closes on save button", async () => {
    const onClose = vi.fn();
    render(<ModelConfigDialog open={true} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByText("保存")).not.toBeNull();
    });

    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      expect(putModelPref).toHaveBeenCalledWith({ primary: null, fallback: null });
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("does not save when closed via cancel", async () => {
    const onClose = vi.fn();
    render(<ModelConfigDialog open={true} onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByText("取消")).not.toBeNull();
    });

    fireEvent.click(screen.getByText("取消"));
    expect(onClose).toHaveBeenCalled();
    expect(putModelPref).not.toHaveBeenCalled();
  });
});
