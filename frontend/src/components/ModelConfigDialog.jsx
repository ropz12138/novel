import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getModels, getModelPref, putModelPref } from "../lib/canvasApi";

export default function ModelConfigDialog({ open, onClose }) {
  const [available, setAvailable] = useState([]);
  const [defaultPrimary, setDefaultPrimary] = useState("");
  const [defaultFallback, setDefaultFallback] = useState("");
  const [primary, setPrimary] = useState(null);
  const [fallback, setFallback] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([getModels(), getModelPref()])
      .then(([modelsData, prefData]) => {
        if (cancelled) return;
        setAvailable(modelsData.available_models || []);
        setDefaultPrimary(modelsData.default_primary || "");
        setDefaultFallback(modelsData.default_fallback || "");
        setPrimary(prefData.primary);
        setFallback(prefData.fallback);
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleSave = async () => {
    setError("");
    if (primary && fallback && primary === fallback) {
      setError("主模型与备模型不能相同");
      return;
    }
    setSaving(true);
    try {
      await putModelPref({ primary, fallback });
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const labelOf = (name, isPrimary) => {
    if (!name) return "";
    const def = isPrimary ? defaultPrimary : defaultFallback;
    return name === def ? `${name}（默认）` : name;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-800">模型配置</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {loading ? (
          <div className="py-8 text-center text-sm text-gray-500">加载中...</div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                主模型
              </label>
              <select
                value={primary ?? ""}
                onChange={(e) => setPrimary(e.target.value || null)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">使用默认（{defaultPrimary}）</option>
                {available.map((m) => (
                  <option key={m} value={m}>
                    {labelOf(m, true)}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                备模型（主模型 429 限流时自动切换）
              </label>
              <select
                value={fallback ?? ""}
                onChange={(e) => setFallback(e.target.value || null)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">使用默认（{defaultFallback || "无"}）</option>
                {available.map((m) => (
                  <option key={m} value={m}>
                    {labelOf(m, false)}
                  </option>
                ))}
              </select>
            </div>

            {error && (
              <p className="text-sm text-red-500">{error}</p>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={onClose}
                className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="rounded-lg bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
