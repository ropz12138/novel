import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Gauge } from "lucide-react";
import { subscribeAppBack } from "../lib/appBackNavigation";
import { tokenUsageApi } from "../lib/tokenUsageApi";
import { IS_NATIVE_APP } from "../lib/runtime-config";

const COLUMNS = [
  ["cached_input_tokens", "缓存输入", "#4f46e5"],
  ["uncached_input_tokens", "未缓存输入", "#64748b"],
  ["output_tokens", "输出", "#d97706"],
];

function formatTokens(value) {
  return Number(value).toLocaleString("zh-CN");
}

function formatPercent(value) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(1)}%`;
}

function formatLatency(value) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toLocaleString("zh-CN")} ms`;
}

function formatSpeed(value) {
  if (value === null || value === undefined) return "—";
  return `${Number(value).toFixed(2)} token/s`;
}

function formatBucketLabel(bucket, grain) {
  if (grain === "hour") {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})/.exec(bucket);
    if (!match) return bucket;
    return `${match[2]}-${match[3]} ${match[4]}:00`;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(bucket);
  if (!match) return bucket;
  return `${match[2]}-${match[3]}`;
}

function ModelUsageChart({ model, points, grain }) {
  const chartHeight = 120;
  const tooltipHeight = 22;
  const barWidth = 16;
  const barGap = 4;
  const groupGap = 28;
  const groupWidth = COLUMNS.length * barWidth + (COLUMNS.length - 1) * barGap;
  const width = Math.max(points.length * groupWidth + Math.max(points.length - 1, 0) * groupGap, groupWidth);
  const max = Math.max(...points.flatMap((point) => COLUMNS.map(([key]) => Number(point[key]) || 0)), 0);
  const scale = max === 0 ? 0 : chartHeight / max;
  const [activeBar, setActiveBar] = useState(null);

  return (
    <div data-testid={`token-usage-row-${model}`} className="min-w-0">
      <h2 className="mb-2 text-sm font-semibold text-slate-800">{model}</h2>
      <div className="overflow-x-auto">
        <svg
          role="img"
          aria-label={`${model} Token 用量`}
          viewBox={`0 0 ${width} ${tooltipHeight + chartHeight + 32}`}
          className="h-40"
          style={{ width: Math.max(width, 280) }}
        >
          {points.map((point, groupIndex) => {
            const origin = groupIndex * (groupWidth + groupGap);
            return (
              <g key={point.bucket}>
                {COLUMNS.map(([key, label, color], barIndex) => {
                  const value = Number(point[key]) || 0;
                  const height = value * scale;
                  const x = origin + barIndex * (barWidth + barGap);
                  const barId = `${point.bucket}:${key}`;
                  const tip = `${label} ${formatTokens(value)}`;
                  const tipWidth = Math.max(barWidth + 12, tip.length * 7 + 12);
                  const tipX = Math.min(Math.max(x + barWidth / 2 - tipWidth / 2, 0), Math.max(width - tipWidth, 0));
                  const tipY = Math.max(2, tooltipHeight + chartHeight - height - tooltipHeight);
                  const showTip = () => setActiveBar(barId);
                  const hideTip = () => setActiveBar((current) => (current === barId ? null : current));
                  return (
                    <g key={key}>
                      <rect
                        data-testid={`bar-${model}-${point.bucket}-${key}`}
                        x={x}
                        y={tooltipHeight + chartHeight - height}
                        width={barWidth}
                        height={height}
                        fill={color}
                        rx="2"
                        onMouseEnter={showTip}
                        onMouseLeave={hideTip}
                      />
                      <rect
                        x={x}
                        y={tooltipHeight}
                        width={barWidth}
                        height={chartHeight}
                        fill="transparent"
                        onMouseEnter={showTip}
                        onMouseLeave={hideTip}
                      />
                      {activeBar === barId && (
                        <g data-testid={`bar-tip-${model}-${point.bucket}-${key}`} pointerEvents="none">
                          <rect x={tipX} y={tipY} width={tipWidth} height={18} rx="4" fill="#0f172a" />
                          <text
                            x={tipX + tipWidth / 2}
                            y={tipY + 13}
                            textAnchor="middle"
                            fontSize="11"
                            fill="#ffffff"
                          >
                            {tip}
                          </text>
                        </g>
                      )}
                    </g>
                  );
                })}
                <text x={origin} y={tooltipHeight + chartHeight + 18} fontSize="11" fill="#334155">
                  {formatBucketLabel(point.bucket, grain)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export function TokenUsagePage({ appMode = IS_NATIVE_APP }) {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [series, setSeries] = useState([]);
  const [works, setWorks] = useState([]);
  const [workId, setWorkId] = useState("");
  const [grain, setGrain] = useState("day");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    tokenUsageApi.getUsage(workId || undefined, grain)
      .then((data) => {
        if (cancelled) return;
        setModels(data.models || []);
        setSeries(data.series);
        setWorks(data.works || []);
      })
      .catch((err) => {
        if (!cancelled) {
          setModels(null);
          setError(err?.message || "加载 Token 用量失败");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workId, grain]);

  useEffect(() => {
    if (!appMode) return undefined;
    let disposed = false;
    let unsubscribe;
    const handleBack = () => {
      navigate("/");
    };
    subscribeAppBack(handleBack).then((remove) => {
      if (disposed) remove();
      else unsubscribe = remove;
    });
    return () => {
      disposed = true;
      unsubscribe?.();
    };
  }, [appMode, navigate]);

  return (
    <div className="flex h-screen flex-col bg-slate-50">
      <header
        data-testid={appMode ? "token-usage-app-header" : undefined}
        className={`flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 ${
          appMode
            ? "pb-3 pt-[max(2.75rem,calc(env(safe-area-inset-top)+0.75rem))]"
            : "h-14"
        }`}
      >
        <Link
          to="/"
          aria-label="返回创作画布"
          className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <Gauge className="h-5 w-5 text-indigo-600" />
        <h1 className="font-semibold text-slate-800">Token 用量</h1>
      </header>

      <main className={`min-h-0 flex-1 overflow-y-auto px-4 py-4 ${appMode ? "pb-[max(1.5rem,env(safe-area-inset-bottom))]" : ""}`}>
        {error && (
          <div className="rounded-lg border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {!error && models === null && (
          <div className="text-sm text-slate-500">加载中...</div>
        )}
        {!error && models && (
          <div className="flex flex-col gap-4">
            <label className="flex items-center gap-2 text-sm text-slate-600">
              作品
              <select
                aria-label="作品"
                value={workId}
                onChange={(event) => setWorkId(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
              >
                <option value="">全部作品</option>
                {works.map((work) => (
                  <option key={work.id} value={work.id}>{work.title}</option>
                ))}
              </select>
            </label>

            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap gap-3 text-xs text-slate-500">
                  {COLUMNS.map(([key, label, color]) => (
                    <span key={key} className="flex items-center gap-1.5">
                      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: color }} />
                      {label}
                    </span>
                  ))}
                </div>
                <div role="group" aria-label="横坐标" className="flex rounded-lg border border-slate-200 p-0.5">
                  {[
                    ["day", "天"],
                    ["hour", "小时"],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={grain === value}
                      onClick={() => setGrain(value)}
                      className={`rounded-md px-3 py-1 text-sm ${
                        grain === value ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-100"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex flex-col gap-4">
                {series.map((row) => (
                  <ModelUsageChart key={row.model} model={row.model} points={row.points} grain={grain} />
                ))}
              </div>
            </section>

            {appMode ? (
              <div className="flex flex-col gap-3">
                {models.map((row) => (
                  <section key={row.model} className="rounded-xl border border-slate-200 bg-white p-4">
                    <h2 className="text-sm font-semibold text-slate-800">{row.model}</h2>
                    <dl className="mt-3 grid grid-cols-2 gap-2">
                      {COLUMNS.map(([key, label]) => (
                        <div key={key}>
                          <dt className="text-[11px] text-slate-400">{label}</dt>
                          <dd className="mt-1 text-base font-medium text-slate-800">{formatTokens(row[key])}</dd>
                        </div>
                      ))}
                      <div>
                        <dt className="text-[11px] text-slate-400">缓存占比</dt>
                        <dd className="mt-1 text-base font-medium text-slate-800">{formatPercent(row.cached_input_percent)}</dd>
                      </div>
                      <div>
                        <dt className="text-[11px] text-slate-400">平均端到端速度</dt>
                        <dd className="mt-1 text-base font-medium text-slate-800">{formatSpeed(row.average_output_tokens_per_second)}</dd>
                      </div>
                      <div>
                        <dt className="text-[11px] text-slate-400">最近端到端速度</dt>
                        <dd className="mt-1 text-base font-medium text-slate-800">{formatSpeed(row.latest_output_tokens_per_second)}</dd>
                      </div>
                      <div>
                        <dt className="text-[11px] text-slate-400">平均首 Token</dt>
                        <dd className="mt-1 text-base font-medium text-slate-800">{formatLatency(row.average_time_to_first_token_ms)}</dd>
                      </div>
                      <div>
                        <dt className="text-[11px] text-slate-400">最近首 Token</dt>
                        <dd className="mt-1 text-base font-medium text-slate-800">{formatLatency(row.latest_time_to_first_token_ms)}</dd>
                      </div>
                    </dl>
                  </section>
                ))}
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-slate-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">模型</th>
                      {COLUMNS.map(([, label]) => (
                        <th key={label} className="px-4 py-3 font-medium">{label}</th>
                      ))}
                      <th className="px-4 py-3 font-medium">缓存占比</th>
                      <th className="px-4 py-3 font-medium">平均端到端速度</th>
                      <th className="px-4 py-3 font-medium">最近端到端速度</th>
                      <th className="px-4 py-3 font-medium">平均首 Token</th>
                      <th className="px-4 py-3 font-medium">最近首 Token</th>
                    </tr>
                  </thead>
                  <tbody>
                    {models.map((row) => (
                      <tr key={row.model} className="border-t border-slate-100">
                        <td className="px-4 py-3 font-medium text-slate-800">{row.model}</td>
                        {COLUMNS.map(([key]) => (
                          <td key={key} className="px-4 py-3 text-slate-700">{formatTokens(row[key])}</td>
                        ))}
                        <td className="px-4 py-3 text-slate-700">{formatPercent(row.cached_input_percent)}</td>
                        <td className="px-4 py-3 text-slate-700">{formatSpeed(row.average_output_tokens_per_second)}</td>
                        <td className="px-4 py-3 text-slate-700">{formatSpeed(row.latest_output_tokens_per_second)}</td>
                        <td className="px-4 py-3 text-slate-700">{formatLatency(row.average_time_to_first_token_ms)}</td>
                        <td className="px-4 py-3 text-slate-700">{formatLatency(row.latest_time_to_first_token_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
