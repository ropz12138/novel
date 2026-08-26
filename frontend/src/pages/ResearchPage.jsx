import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowLeft,
  Activity,
  AlertTriangle,
  BookOpen,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CirclePause,
  Download,
  FileText,
  LoaderCircle,
  MessageSquarePlus,
  Play,
  Sparkles,
  Upload,
  UserRound,
  Wrench,
  XCircle,
} from "lucide-react";
import { researchApi } from "../lib/researchApi";
import { authFetch } from "../lib/authFetch";

const STATUS_LABELS = {
  queued: "等待启动",
  running: "分析中",
  paused: "已暂停",
  completed: "已完成",
  error: "发生错误",
};

const STATUS_STYLES = {
  queued: "bg-slate-100 text-slate-600",
  running: "bg-blue-100 text-blue-700",
  paused: "bg-amber-100 text-amber-700",
  completed: "bg-emerald-100 text-emerald-700",
  error: "bg-red-100 text-red-700",
};

const ARTIFACT_LABELS = {
  reading_plan: "阅读计划",
  reading_note: "阅读笔记",
  stage_summary: "阶段总结",
  book_overview: "全书概览",
  structure_report: "结构分析",
  character_report: "角色分析",
  technique_card: "技法卡",
  final_report: "最终报告",
};

function formatTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function parseJson(value, fallback = {}) {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return fallback;
  }
}

function formatToolName(name) {
  const labels = {
    inspect_novel_text: "采样查看文本",
    grep_novel_text: "搜索小说原文",
    create_cleaned_copy: "创建整理副本",
    transform_novel_text: "清理与转换文本",
    get_book_profile: "分析章节结构",
    normalize_novel_sections: "整理章节并建立索引",
    edit_novel_text: "编辑整理文本",
    diff_novel_versions: "比较文本版本",
    read_novel_sections: "阅读小说章节",
    save_research_artifact: "保存研究产出",
    list_research_artifacts: "查看产出目录",
    read_research_artifacts: "读取已有产出",
    update_working_memory: "更新长期工作记忆",
    update_research_progress: "更新研究进度",
    complete_research: "完成全书研究",
  };
  return labels[name] || name || "执行工具";
}

function EventHeader({ icon: Icon, label, time, className = "" }) {
  return (
    <div className={`flex items-center gap-1.5 text-[11px] font-medium ${className}`}>
      <Icon className="h-3.5 w-3.5" />
      <span>{label}</span>
      <span className="font-normal opacity-60">{formatTime(time)}</span>
    </div>
  );
}

function ProgressBar({ job }) {
  const hasTotal = job.progress_total > 0;
  const ratio = hasTotal
    ? Math.min(100, Math.round((job.progress_current / job.progress_total) * 100))
    : 0;
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500">
        <span>{job.stage || "准备中"}</span>
        <span>
          {hasTotal
            ? `${job.progress_current}/${job.progress_total} ${job.progress_unit}`
            : job.status === "running" ? "持续执行" : ""}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        {hasTotal ? (
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-500"
            style={{ width: `${ratio}%` }}
          />
        ) : job.status === "running" ? (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-blue-400" />
        ) : null}
      </div>
      {job.progress_detail && (
        <p className="mt-2 text-xs leading-5 text-slate-500">{job.progress_detail}</p>
      )}
    </div>
  );
}

function EventItem({ event }) {
  const meta = parseJson(event.meta_text);

  if (event.event_type === "agent") {
    return (
      <div className="flex items-start gap-2.5">
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-600">
          <Bot className="h-3.5 w-3.5" />
        </div>
        <div className="max-w-[88%] rounded-2xl rounded-tl-md bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
          <EventHeader
            icon={Sparkles}
            label="研究 Agent"
            time={event.created_at}
            className="mb-1.5 text-blue-600"
          />
          <div className="prose prose-slate max-w-none text-sm leading-6">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {event.content}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  if (event.event_type === "instruction") {
    return (
      <div className="flex items-start justify-end gap-2.5">
        <div className="max-w-[82%] rounded-2xl rounded-tr-md bg-indigo-600 px-4 py-3 text-white shadow-sm">
          <EventHeader
            icon={UserRound}
            label="你的追加要求"
            time={event.created_at}
            className="mb-1.5 text-indigo-100"
          />
          <div className="whitespace-pre-wrap text-sm leading-6">{event.content}</div>
        </div>
        <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600">
          <UserRound className="h-3.5 w-3.5" />
        </div>
      </div>
    );
  }

  if (event.event_type === "tool_result") {
    const result = parseJson(event.content, null);
    const failed = result?.success === false || Boolean(result?.error);
    const summary = failed
      ? result?.error || "工具执行失败"
      : result?.preview
        ? "预览完成，尚未修改文本"
        : result?.title
          ? `已生成：${result.title}`
          : "执行完成";
    return (
      <details
        className={`group ml-9 rounded-xl border px-3 py-2 ${
          failed
            ? "border-red-200 bg-red-50/70"
            : "border-emerald-200 bg-emerald-50/60"
        }`}
      >
        <summary className="flex cursor-pointer list-none items-center gap-2">
          {failed ? (
            <XCircle className="h-4 w-4 shrink-0 text-red-500" />
          ) : (
            <Check className="h-4 w-4 shrink-0 text-emerald-600" />
          )}
          <span className={`text-xs font-medium ${failed ? "text-red-700" : "text-emerald-700"}`}>
            {formatToolName(meta.tool)}
          </span>
          <span className={`min-w-0 flex-1 truncate text-[11px] ${failed ? "text-red-500" : "text-emerald-600"}`}>
            {summary}
          </span>
          <span className="text-[10px] text-slate-400">{formatTime(event.created_at)}</span>
          <ChevronDown className="h-3.5 w-3.5 text-slate-400 transition-transform group-open:rotate-180" />
        </summary>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-5 text-slate-600">
          {result ? JSON.stringify(result, null, 2) : event.content}
        </pre>
      </details>
    );
  }

  if (event.event_type === "tool_call") {
    const toolName = meta.tool;
    return (
      <details className="group ml-9 rounded-lg border border-slate-200 bg-slate-100/70 px-3 py-2">
        <summary className="flex cursor-pointer list-none items-center gap-2">
          <Wrench className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          <span className="flex-1 text-xs font-medium text-slate-600">
            {formatToolName(toolName)}
          </span>
          <span className="text-[10px] text-slate-400">{formatTime(event.created_at)}</span>
          <ChevronDown className="h-3.5 w-3.5 text-slate-400 transition-transform group-open:rotate-180" />
        </summary>
        <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words border-t border-slate-200 pt-2 text-[11px] leading-5 text-slate-500">
          {JSON.stringify(meta.args || {}, null, 2)}
        </pre>
      </details>
    );
  }

  if (event.event_type === "progress") {
    const current = meta.current || 0;
    const total = meta.total || 0;
    return (
      <div className="ml-9 rounded-xl border border-violet-200 bg-violet-50 px-3.5 py-3">
        <EventHeader
          icon={Activity}
          label={meta.stage || "研究进度"}
          time={event.created_at}
          className="mb-1 text-violet-700"
        />
        <div className="flex items-center justify-between gap-3 text-xs text-violet-700">
          <span>{event.content}</span>
          {total > 0 && <span className="shrink-0 font-medium">{current}/{total} {meta.unit}</span>}
        </div>
      </div>
    );
  }

  if (event.event_type === "artifact") {
    return (
      <div className="ml-9 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-3">
        <EventHeader
          icon={FileText}
          label="新增研究产出"
          time={event.created_at}
          className="mb-1 text-emerald-700"
        />
        <div className="text-sm font-medium text-emerald-800">{event.content}</div>
      </div>
    );
  }

  const isError = ["error", "retry"].includes(event.event_type);
  const isComplete = event.event_type === "completed";
  const isPaused = event.event_type === "paused";
  const StateIcon = isError
    ? AlertTriangle
    : isComplete
      ? CheckCircle2
      : isPaused
        ? CirclePause
        : Bot;
  const stateLabel = {
    started: "Agent 已启动",
    paused: "任务已中断",
    completed: "全书分析完成",
    error: "运行错误",
    retry: "自动重试",
    continue: "继续推进",
  }[event.event_type] || event.event_type;
  return (
    <div
      className={`ml-9 rounded-xl border px-3.5 py-3 ${
        isError
          ? "border-red-200 bg-red-50 text-red-700"
          : isComplete
            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
            : isPaused
              ? "border-amber-200 bg-amber-50 text-amber-700"
              : "border-slate-200 bg-white text-slate-600"
      }`}
    >
      <EventHeader icon={StateIcon} label={stateLabel} time={event.created_at} className="mb-1" />
      <div className="whitespace-pre-wrap text-sm leading-6">
        {event.content}
      </div>
    </div>
  );
}

export function ResearchPage() {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const dragDepthRef = useRef(0);
  const eventJobIdRef = useRef(null);
  const lastEventSequenceRef = useRef(0);
  const [jobs, setJobs] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [job, setJob] = useState(null);
  const [events, setEvents] = useState([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState(null);
  const [instruction, setInstruction] = useState("");
  const [uploading, setUploading] = useState(false);
  const [draggingFile, setDraggingFile] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState("");

  const loadJobs = useCallback(async () => {
    const result = await researchApi.listJobs();
    const rows = result.jobs || [];
    setJobs(rows);
    setSelectedId((current) => current || rows[0]?.id || null);
    return rows;
  }, []);

  const loadSelected = useCallback(async (jobId, { resetEvents = false } = {}) => {
    if (!jobId) {
      eventJobIdRef.current = null;
      lastEventSequenceRef.current = 0;
      setJob(null);
      setEvents([]);
      return;
    }

    if (resetEvents || eventJobIdRef.current !== jobId) {
      eventJobIdRef.current = jobId;
      lastEventSequenceRef.current = 0;
      setEvents([]);
    }
    const after = lastEventSequenceRef.current;
    const [detail, eventResult] = await Promise.all([
      researchApi.getJob(jobId),
      researchApi.getEvents(jobId, after),
    ]);
    if (eventJobIdRef.current !== jobId) return;

    setJob(detail);
    const incoming = eventResult.events || [];
    if (incoming.length) {
      lastEventSequenceRef.current = Math.max(
        lastEventSequenceRef.current,
        ...incoming.map((item) => item.sequence || 0),
      );
      setEvents((current) => {
        const bySequence = new Map(
          current.map((item) => [item.sequence, item]),
        );
        incoming.forEach((item) => bySequence.set(item.sequence, item));
        return [...bySequence.values()].sort(
          (left, right) => left.sequence - right.sequence,
        );
      });
    }
    setSelectedArtifactId((current) => {
      if (current && detail.artifacts?.some((item) => item.id === current)) {
        return current;
      }
      return detail.artifacts?.[0]?.id || null;
    });
  }, []);

  useEffect(() => {
    loadJobs().catch((err) => setError(err.message));
  }, [loadJobs]);

  useEffect(() => {
    loadSelected(selectedId, { resetEvents: true }).catch(
      (err) => setError(err.message),
    );
  }, [selectedId, loadSelected]);

  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        const rows = await loadJobs();
        if (selectedId && rows.some((item) => item.id === selectedId)) {
          await loadSelected(selectedId);
        }
      } catch {
        // 轮询失败时保留当前页面内容
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [selectedId, loadJobs, loadSelected]);

  const uploadFile = useCallback(async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt")) {
      setError("第一版仅支持 TXT 文件");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const created = await researchApi.upload(file);
      await loadJobs();
      setSelectedId(created.job_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }, [loadJobs]);

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    await uploadFile(file);
  };

  const handleDragEnter = (event) => {
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current += 1;
    if (event.dataTransfer?.types?.includes("Files")) {
      setDraggingFile(true);
    }
  };

  const handleDragOver = (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "copy";
    }
  };

  const handleDragLeave = (event) => {
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setDraggingFile(false);
    }
  };

  const handleDrop = async (event) => {
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = 0;
    setDraggingFile(false);
    const files = Array.from(event.dataTransfer?.files || []);
    if (files.length === 0) return;
    if (files.length > 1) {
      setError("一次只能上传一份小说 TXT");
      return;
    }
    await uploadFile(files[0]);
  };

  const handlePause = async () => {
    if (!job) return;
    setActionBusy(true);
    try {
      await researchApi.pause(job.id);
      await loadSelected(job.id);
      await loadJobs();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionBusy(false);
    }
  };

  const handleContinue = async () => {
    const message = instruction.trim();
    if (!job || !message) return;
    setActionBusy(true);
    try {
      await researchApi.continue(job.id, message);
      setInstruction("");
      await loadSelected(job.id);
      await loadJobs();
    } catch (err) {
      setError(err.message);
    } finally {
      setActionBusy(false);
    }
  };

  const handleDownload = async (versionId) => {
    if (!job) return;
    try {
      const response = await authFetch(
        researchApi.downloadUrl(job.id, versionId),
      );
      if (!response.ok) throw new Error("下载失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  };

  const selectedArtifact = useMemo(
    () => job?.artifacts?.find((item) => item.id === selectedArtifactId) || null,
    [job, selectedArtifactId],
  );

  return (
    <div
      className="relative flex h-screen flex-col bg-slate-50"
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {draggingFile && (
        <div className="pointer-events-none absolute inset-0 z-[100] flex items-center justify-center bg-indigo-950/35 p-8 backdrop-blur-[2px]">
          <div className="flex h-full w-full max-w-4xl flex-col items-center justify-center rounded-3xl border-2 border-dashed border-white bg-indigo-600/90 text-white shadow-2xl">
            <div className="mb-5 flex h-20 w-20 items-center justify-center rounded-3xl bg-white/15">
              <Upload className="h-10 w-10" />
            </div>
            <div className="text-2xl font-semibold">松开鼠标，上传小说 TXT</div>
            <div className="mt-3 text-sm text-indigo-100">
              上传完成后，研究 Agent 会自动开始整理和分析
            </div>
          </div>
        </div>
      )}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-5">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate("/")}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
            title="返回创作画布"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-indigo-600" />
            <h1 className="font-semibold text-slate-800">小说研究 Agent</h1>
          </div>
          <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-600">
            独立运行
          </span>
        </div>
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {uploading ? (
            <LoaderCircle className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
          上传小说 TXT
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".txt,text/plain"
          className="hidden"
          onChange={handleUpload}
        />
      </header>

      {error && (
        <div className="border-b border-red-100 bg-red-50 px-5 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <main className="flex min-h-0 flex-1">
        <aside className="w-72 shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-3">
          <div className="mb-2 px-2 text-xs font-medium uppercase tracking-wide text-slate-400">
            研究任务
          </div>
          {jobs.length === 0 ? (
            <button
              onClick={() => inputRef.current?.click()}
              className="w-full rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 hover:border-indigo-300 hover:bg-indigo-50/40"
            >
              上传一份小说后，Agent会自动开始整理和分析
            </button>
          ) : (
            <div className="space-y-1.5">
              {jobs.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  className={`w-full rounded-xl border px-3 py-3 text-left transition-colors ${
                    selectedId === item.id
                      ? "border-indigo-200 bg-indigo-50"
                      : "border-transparent hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-800">
                        {item.original_filename}
                      </div>
                      <div className="mt-1 truncate text-xs text-slate-400">
                        {item.stage}
                      </div>
                    </div>
                    <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-slate-300" />
                  </div>
                  <span
                    className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-[10px] ${
                      STATUS_STYLES[item.status] || STATUS_STYLES.queued
                    }`}
                  >
                    {STATUS_LABELS[item.status] || item.status}
                  </span>
                </button>
              ))}
            </div>
          )}
        </aside>

        {!job ? (
          <section className="flex flex-1 items-center justify-center">
            <div className="max-w-md text-center">
              <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-100">
                <FileText className="h-8 w-8 text-indigo-600" />
              </div>
              <h2 className="text-lg font-semibold text-slate-800">上传完整小说</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">
                Agent会自主识别格式、创建整理副本、逐步阅读并持续生成研究产出。
              </p>
            </div>
          </section>
        ) : (
          <>
            <section className="flex min-w-0 flex-[1.15] flex-col border-r border-slate-200">
              <div className="border-b border-slate-200 bg-white p-4">
                <div className="mb-3 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h2 className="truncate font-semibold text-slate-800">
                      {job.original_filename}
                    </h2>
                    <div className="mt-1 flex items-center gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          STATUS_STYLES[job.status] || STATUS_STYLES.queued
                        }`}
                      >
                        {STATUS_LABELS[job.status] || job.status}
                      </span>
                      <span className="text-xs text-slate-400">
                        {job.versions?.length || 0} 个文本版本
                      </span>
                    </div>
                  </div>
                  {job.status === "running" && (
                    <button
                      onClick={handlePause}
                      disabled={actionBusy}
                      className="flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                    >
                      <CirclePause className="h-3.5 w-3.5" />
                      中断
                    </button>
                  )}
                </div>
                <ProgressBar job={job} />

                {job.versions?.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {job.versions.map((version) => (
                      <button
                        key={version.id}
                        onClick={() => handleDownload(version.id)}
                        className="flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-500 hover:border-indigo-200 hover:text-indigo-600"
                      >
                        <Download className="h-3 w-3" />
                        {version.kind === "raw"
                          ? "原始TXT"
                          : `整理版 v${version.version_number}`}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/80 px-4 py-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-600">
                  <Activity className="h-3.5 w-3.5 text-indigo-500" />
                  Agent 执行动态
                </div>
                <div className="flex items-center gap-3 text-[10px] text-slate-400">
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-blue-400" />
                    思考与说明
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-slate-400" />
                    工具步骤
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-violet-400" />
                    阅读进度
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    研究产出
                  </span>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                <div className="space-y-2.5">
                  {events.map((event) => (
                    <EventItem key={event.id} event={event} />
                  ))}
                  {job.status === "running" && (
                    <div className="flex items-center gap-2 py-3 text-xs text-indigo-500">
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                      Agent会持续工作，直到完成整本小说分析
                    </div>
                  )}
                </div>
              </div>

              <div className="border-t border-slate-200 bg-white p-3">
                <div className="flex gap-2">
                  <textarea
                    value={instruction}
                    onChange={(event) => setInstruction(event.target.value)}
                    rows={2}
                    placeholder={
                      job.status === "paused"
                        ? "补充要求，例如：重点分析感情线，然后继续……"
                        : "随时追加要求，Agent会在下一步吸收……"
                    }
                    className="min-h-[58px] flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                  />
                  <button
                    onClick={handleContinue}
                    disabled={!instruction.trim() || actionBusy}
                    className="flex w-24 shrink-0 flex-col items-center justify-center gap-1 rounded-lg bg-indigo-600 text-xs text-white hover:bg-indigo-700 disabled:opacity-40"
                  >
                    {job.status === "paused" || job.status === "error" ? (
                      <Play className="h-4 w-4" />
                    ) : (
                      <MessageSquarePlus className="h-4 w-4" />
                    )}
                    {job.status === "paused" || job.status === "error"
                      ? "要求并继续"
                      : "追加要求"}
                  </button>
                </div>
              </div>
            </section>

            <section className="flex min-w-0 flex-1 flex-col bg-white">
              <div className="border-b border-slate-200 px-4 py-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  <h3 className="text-sm font-semibold text-slate-700">研究产出</h3>
                  <span className="text-xs text-slate-400">
                    {job.artifacts?.length || 0}
                  </span>
                </div>
              </div>
              <div className="flex min-h-0 flex-1">
                <div className="w-52 shrink-0 overflow-y-auto border-r border-slate-100 p-2">
                  {job.artifacts?.length ? (
                    job.artifacts.map((artifact) => (
                      <button
                        key={artifact.id}
                        onClick={() => setSelectedArtifactId(artifact.id)}
                        className={`mb-1 w-full rounded-lg px-3 py-2 text-left ${
                          selectedArtifactId === artifact.id
                            ? "bg-indigo-50 text-indigo-700"
                            : "text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        <div className="text-[10px] uppercase tracking-wide opacity-60">
                          {ARTIFACT_LABELS[artifact.artifact_type]
                            || artifact.artifact_type}
                        </div>
                        <div className="mt-0.5 line-clamp-2 text-xs font-medium leading-5">
                          {artifact.title}
                        </div>
                      </button>
                    ))
                  ) : (
                    <div className="px-3 py-8 text-center text-xs leading-5 text-slate-400">
                      Agent完成首批阅读后，产出会出现在这里
                    </div>
                  )}
                </div>
                <article className="min-w-0 flex-1 overflow-y-auto p-5">
                  {selectedArtifact ? (
                    <>
                      <div className="mb-4 border-b border-slate-100 pb-4">
                        <div className="text-xs font-medium text-indigo-500">
                          {ARTIFACT_LABELS[selectedArtifact.artifact_type]
                            || selectedArtifact.artifact_type}
                        </div>
                        <h2 className="mt-1 text-lg font-semibold text-slate-800">
                          {selectedArtifact.title}
                        </h2>
                        <div className="mt-1 text-xs text-slate-400">
                          {formatTime(selectedArtifact.created_at)}
                        </div>
                      </div>
                      <div className="prose prose-slate max-w-none text-sm leading-7">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {selectedArtifact.content}
                        </ReactMarkdown>
                      </div>
                    </>
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-slate-400">
                      选择一项研究产出查看完整内容
                    </div>
                  )}
                </article>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
