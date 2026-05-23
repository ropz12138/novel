import { API_BASE } from "../lib/runtime-config";
import { authFetch } from "../lib/authFetch";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Bot,
  BookOpen,
  Calendar,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  LayoutList,
  Loader2,
  PenLine,
  Plus,
  Save,
  Send,
  Sparkles,
  Trash2,
  Users,
  X,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { DiffViewer } from "../components/agent/DiffViewer";
import { OutlineDiffViewer } from "../components/agent/OutlineDiffViewer";
import { CharacterDiffViewer } from "../components/agent/CharacterDiffViewer";
import { extractChapterNumbers } from "../lib/chapterOutline";
import { parsePositiveChapterInt } from "../lib/outlineChapterInput";
import { relationGraphStabilizationFallbackMs } from "../lib/relationGraphLoading";
import { sortTimelineNodes } from "../lib/outlineTimelineSort";
import { buildGraphData } from "../lib/buildGraphData";
import { handleOutlineEditDiff, handleCharacterEditDiff, handleTodolistGenerated } from "../lib/sseEventHandlers";
import { sessionApi } from "../lib/api";
import { CharacterDetailDrawer } from "../components/CharacterDetailDrawer";
import { RelationGraphLoadingOverlay } from "../components/RelationGraphLoadingOverlay";


let visNetworkLoadPromise = null;

function ensureVisNetworkLoaded() {
  if (typeof window !== "undefined" && window.vis?.Network) return Promise.resolve(window.vis);
  if (visNetworkLoadPromise) return visNetworkLoadPromise;
  visNetworkLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js";
    script.async = true;
    script.onload = () => resolve(window.vis);
    script.onerror = () => reject(new Error("vis-network 加载失败"));
    document.head.appendChild(script);
  });
  return visNetworkLoadPromise;
}


function toGraphNodeId(focus) {
  if (!focus?.type || !focus?.id) return null;
  if (focus.type === "timeline") return `t::${focus.id}`;
  if (focus.type === "branch") return `b::${focus.id}`;
  if (focus.type === "foreshadowing") return `f::${focus.id}`;
  if (focus.type === "character") return `c::${focus.id}`;
  return null;
}

function fromGraphNodeId(graphNodeId) {
  const raw = String(graphNodeId || "");
  const [prefix, , id] = raw.split(":");
  if (!prefix || !id) return null;
  if (prefix === "t") return { type: "timeline", id };
  if (prefix === "b") return { type: "branch", id };
  if (prefix === "f") return { type: "foreshadowing", id };
  if (prefix === "c") return { type: "character", id };
  return null;
}

function RelationGraphPanel({ tree, characters, focus, pulseFocus, onCharacterSelect, onNodeSelect }) {
  const graphRef = useRef(null);
  const networkRef = useRef(null);
  const highlightNodeRef = useRef(null);
  const resetHighlightsRef = useRef(null);
  const [graphError, setGraphError] = useState("");
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphLoadingPhase, setGraphLoadingPhase] = useState("script");
  const [physicsEnabled, setPhysicsEnabled] = useState(true);

  const graphData = useMemo(() => buildGraphData(tree, characters), [tree, characters]);

  const centerNode = (network, nodeId, scale = 1.05, duration = 260) => {
    try {
      const positions = network.getPositions([nodeId]) || {};
      const p = positions[nodeId];
      if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) {
        network.moveTo({
          position: { x: p.x, y: p.y },
          scale,
          animation: { duration },
        });
      } else {
        network.focus(nodeId, { scale, animation: { duration } });
      }
    } catch {
      // noop
    }
  };

  useEffect(() => {
    let cancelled = false;
    let fallbackTimer = null;

    const finishLoading = () => {
      if (!cancelled) setGraphLoading(false);
    };

    setGraphLoading(true);
    setGraphLoadingPhase("script");
    setGraphError("");

    const mount = async () => {
      try {
        const vis = await ensureVisNetworkLoaded();
        if (cancelled || !graphRef.current) return;
        setGraphLoadingPhase("layout");
        const nodes = new vis.DataSet(graphData.nodes);
        const edges = new vis.DataSet(graphData.edges);
        const options = {
          groups: {
            character: {
              color: { background: "#f5f3ff", border: "#7c3aed", highlight: { background: "#ede9fe", border: "#7c3aed" } },
              font: { color: "#4c1d95", size: 12 },
              borderWidth: 2,
              margin: 10,
            },
            mainStory: {
              color: { background: "#eff6ff", border: "#2563eb", highlight: { background: "#dbeafe", border: "#2563eb" } },
              font: { color: "#1e3a8a", size: 12 },
              borderWidth: 1.5,
              margin: 8,
            },
            branchStory: {
              color: { background: "#f0fdf4", border: "#059669" },
              font: { color: "#065f46", size: 11 },
              borderWidth: 1.5,
              margin: 8,
            },
            foreshadow: {
              color: { background: "#fffbeb", border: "#d97706" },
              font: { color: "#78350f", size: 10 },
              borderWidth: 1.5,
            },
          },
          edges: {
            smooth: { type: "cubicBezier", roundness: 0.35 },
            font: { size: 10, color: "#64748b", align: "middle" },
          },
          physics: {
            enabled: physicsEnabled,
            barnesHut: {
              gravitationalConstant: -2500,
              springLength: 130,
              springConstant: 0.04,
            },
            stabilization: { iterations: 150 },
          },
          interaction: { hover: true, tooltipDelay: 150, selectConnectedEdges: false },
        };
        const network = new vis.Network(graphRef.current, { nodes, edges }, options);
        const originalNodeColors = new Map();
        const originalEdgeColors = new Map();
        nodes.get().forEach((n) => originalNodeColors.set(n.id, n.color));
        edges.get().forEach((e) => originalEdgeColors.set(e.id, e.color));

        const resetHighlights = () => {
          const nodeUpdates = nodes.get().map((n) => ({
            id: n.id,
            color: originalNodeColors.get(n.id),
          }));
          const edgeUpdates = edges.get().map((e) => ({
            id: e.id,
            color: originalEdgeColors.get(e.id),
            hidden: false,
          }));
          nodes.update(nodeUpdates);
          edges.update(edgeUpdates);
        };

        const dimOthers = (selectedId) => {
          const connectedNodes = new Set(network.getConnectedNodes(selectedId) || []);
          const connectedEdges = new Set(network.getConnectedEdges(selectedId) || []);
          connectedNodes.add(selectedId);
          const nodeUpdates = nodes.get().map((n) => {
            if (connectedNodes.has(n.id)) return { id: n.id, color: originalNodeColors.get(n.id) };
            const base = originalNodeColors.get(n.id) || {};
            return {
              id: n.id,
              color: {
                ...base,
                background: "rgba(203,213,225,0.25)",
                border: "rgba(148,163,184,0.35)",
              },
            };
          });
          const edgeUpdates = edges.get().map((e) => {
            if (connectedEdges.has(e.id)) return { id: e.id, color: originalEdgeColors.get(e.id), hidden: false };
            return { id: e.id, hidden: true };
          });
          nodes.update(nodeUpdates);
          edges.update(edgeUpdates);
        };
        resetHighlightsRef.current = resetHighlights;
        highlightNodeRef.current = dimOthers;

        network.on("click", (params) => {
          const selectedId = params.nodes?.[0];
          if (!selectedId) {
            resetHighlights();
            return;
          }
          dimOthers(selectedId);
          onNodeSelect?.(fromGraphNodeId(selectedId));
          if (onCharacterSelect && String(selectedId).startsWith("c:")) {
            const idx = parseInt(String(selectedId).split(":")[1], 10) - 1;
            const chars = Array.isArray(characters) ? characters : [];
            if (idx >= 0 && idx < chars.length) {
              onCharacterSelect(chars[idx]);
            }
          }
        });
        networkRef.current = network;

        const nodeCount = graphData.nodes.length;
        if (nodeCount === 0 || !physicsEnabled) {
          finishLoading();
          return;
        }

        setGraphLoadingPhase("stabilize");
        network.once("stabilizationIterationsDone", finishLoading);
        const fallbackMs = relationGraphStabilizationFallbackMs(nodeCount, physicsEnabled);
        if (fallbackMs > 0) {
          fallbackTimer = setTimeout(finishLoading, fallbackMs);
        }
      } catch (err) {
        setGraphError(err?.message || "关系图加载失败");
        finishLoading();
      }
    };
    mount();
    return () => {
      cancelled = true;
      if (fallbackTimer) clearTimeout(fallbackTimer);
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
      highlightNodeRef.current = null;
      resetHighlightsRef.current = null;
    };
  }, [graphData, physicsEnabled]);

  useEffect(() => {
    const network = networkRef.current;
    if (!network) return;
    const graphHint = toGraphNodeId(focus);
    const graphId = (() => {
      if (!graphHint) return null;
      const [prefix, raw] = graphHint.split("::");
      const candidates = graphData.nodes || [];
      const hit = candidates.find((n) => String(n.id).startsWith(`${prefix}:`) && String(n.id).endsWith(`:${raw}`));
      return hit?.id || null;
    })();
    if (!graphId) {
      network.unselectAll();
      resetHighlightsRef.current?.();
      return;
    }
    try {
      // 临时冻结物理引擎，避免外部联动聚焦后鼠标移动导致抖动
      network.setOptions({ physics: { enabled: false } });
      network.selectNodes([graphId]);
      highlightNodeRef.current?.(graphId);
      centerNode(network, graphId, 1.05, 260);
      const restoreTimer = window.setTimeout(() => {
        try {
          network.setOptions({ physics: { enabled: physicsEnabled } });
        } catch {
          // noop
        }
      }, 320);
      return () => window.clearTimeout(restoreTimer);
    } catch {
      // noop
    }
    return undefined;
  }, [focus, graphData.nodes, physicsEnabled]);

  useEffect(() => {
    const network = networkRef.current;
    if (!network || !pulseFocus?.id) return;
    const graphHint = toGraphNodeId(pulseFocus);
    if (!graphHint) return;
    const [prefix, raw] = graphHint.split("::");
    const hit = (graphData.nodes || []).find(
      (n) => String(n.id).startsWith(`${prefix}:`) && String(n.id).endsWith(`:${raw}`),
    );
    const graphId = hit?.id;
    if (!graphId) return;
    try {
      network.setOptions({ physics: { enabled: false } });
      network.selectNodes([graphId]);
      centerNode(network, graphId, 1.08, 180);
      const timer = window.setTimeout(() => {
        try {
          network.unselectAll();
          network.setOptions({ physics: { enabled: physicsEnabled } });
        } catch {
          // noop
        }
      }, 420);
      return () => window.clearTimeout(timer);
    } catch {
      // noop
    }
    return undefined;
  }, [pulseFocus, graphData.nodes, physicsEnabled]);

  return (
    <section
      className={`rounded-[14px] border border-slate-300 bg-white p-4 shadow-[0_6px_24px_rgba(15,23,42,0.05)] transition ${
        pulseFocus?.id ? "animate-pulse ring-2 ring-blue-300 ring-offset-1" : ""
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-800">角色 × 剧情 动态网状图谱</h3>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => networkRef.current?.stabilize()}
          >
            重置平铺
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => setPhysicsEnabled((v) => !v)}
          >
            {physicsEnabled ? "固定节点" : "解锁节点"}
          </Button>
        </div>
      </div>
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12px] text-slate-600">
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm border border-violet-700 bg-violet-100" />
          角色
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm border border-blue-700 bg-blue-100" />
          主线事件
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm border border-amber-700 bg-amber-100" />
          埋设伏笔
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-0 w-5 border-t-2 border-red-500" />
          稳定羁绊
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-0 w-5 border-t-2 border-dashed border-red-500" />
          潜在背叛
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-0 w-5 border-t-2 border-blue-500" />
          参与主线
        </span>
        <span className="inline-flex items-center gap-1">
          <i className="inline-block h-0 w-5 border-t-2 border-dashed border-amber-500" />
          触发伏笔
        </span>
      </div>
      <div className="relative h-[700px] overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
        {graphError ? (
          <div className="flex h-full items-center justify-center text-sm text-red-500">{graphError}</div>
        ) : (
          <>
            {graphLoading && <RelationGraphLoadingOverlay phase={graphLoadingPhase} />}
            <div ref={graphRef} className={`h-full w-full ${graphLoading ? "invisible" : ""}`} />
          </>
        )}
      </div>
      <div className="mt-2 text-[12px] text-slate-500">可滚轮缩放、拖拽节点；点击节点会高亮其一度关系。</div>
    </section>
  );
}

function CharacterCardsPanel({ characters, onCharacterSelect }) {
  const list = Array.isArray(characters) ? characters : [];
  const [expanded, setExpanded] = useState({});
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold text-slate-800">角色卡</h3>
      {list.length === 0 ? (
        <p className="text-xs text-slate-500">暂无角色设定。</p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((c, idx) => {
            const rel = c.relationships && typeof c.relationships === "object" ? c.relationships : {};
            return (
              <article key={c.id || `${c.name}-${idx}`} className="cursor-pointer rounded-lg border border-slate-200 bg-slate-50 p-3 transition-colors hover:bg-slate-100" onClick={() => onCharacterSelect?.(c)}>
                <div className="truncate text-sm font-semibold text-slate-800">{c.name || "未知角色"}</div>
                <div className="mb-1 truncate text-[11px] text-slate-500">
                  {c.role_type || "配角"} · 首次出场第 {c.first_chapter || 1} 章
                </div>
                {c.current_status && (
                  <p className="truncate text-xs text-slate-600">状态：{c.current_status}</p>
                )}
                {c.current_goal && (
                  <p className="truncate text-xs text-slate-600">目标：{c.current_goal}</p>
                )}
                {Object.keys(rel).length > 0 && (
                  <div className="mt-1 border-t border-slate-200 pt-1 text-[11px] text-slate-600">
                    {Object.entries(rel)
                      .slice(0, 2)
                      .map(([k, v]) => (
                        <div key={`${c.id || c.name}-${k}`} className="truncate">
                          {k}：{String(v)}
                        </div>
                      ))}
                  </div>
                )}
                <button
                  type="button"
                  className="mt-2 text-[11px] text-blue-600 hover:underline"
                  onClick={() =>
                    setExpanded((prev) => ({ ...prev, [c.id || c.name || idx]: !prev[c.id || c.name || idx] }))
                  }
                >
                  {expanded[c.id || c.name || idx] ? "收起详情" : "展开详情"}
                </button>
                {expanded[c.id || c.name || idx] && (
                  <div className="mt-1 space-y-1 border-t border-slate-200 pt-1 text-[11px] text-slate-600">
                    {c.gender && <div className="truncate">性别：{c.gender}</div>}
                    {c.age && <div className="truncate">年龄：{c.age}</div>}
                    {c.appearance && <div className="line-clamp-2">外貌：{c.appearance}</div>}
                    {c.personality && <div className="line-clamp-2">性格：{c.personality}</div>}
                    {c.background && <div className="line-clamp-2">背景：{c.background}</div>}
                    {c.skills && <div className="line-clamp-2">技能：{c.skills}</div>}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ────────────────────────── Editable text helper ────────────────────────── */

function EditableText({ value, onSave, className = "", multiline = false, editable = true }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef(null);

  useEffect(() => {
    if (editing && ref.current) {
      ref.current.focus();
      ref.current.select();
    }
  }, [editing]);

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== value) {
      onSave(trimmed);
    } else {
      setDraft(value);
    }
    setEditing(false);
  };

  if (!editing) {
    return (
      <span
        className={`rounded px-1 transition-colors ${editable ? "cursor-pointer hover:bg-slate-100" : "cursor-default"} ${className}`}
        onClick={() => {
          if (!editable) return;
          setDraft(value);
          setEditing(true);
        }}
        title={editable ? "点击编辑" : undefined}
      >
        {value}
      </span>
    );
  }

  if (multiline) {
    return (
      <Textarea
        ref={ref}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            commit();
          }
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
        className={`min-h-[60px] ${className}`}
      />
    );
  }

  return (
    <Input
      ref={ref}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") {
          setDraft(value);
          setEditing(false);
        }
      }}
      className={className}
    />
  );
}

/* ─────────────────────────── Branch Card ─────────────────────────────── */

/** 支线卡片最大高度（约 13rem）；超出在收起态用省略号，展开/编辑时在框内滚动 */
const BRANCH_CARD_MAX_H = "max-h-52";

function BranchCard({ branch, onUpdate, onDelete, editing = false, onToggleEdit }) {
  const [expanded, setExpanded] = useState(false);
  const isOpen = editing || expanded;
  const isLeft = branch.side === "left";
  const borderColor = isLeft ? "border-amber-300" : "border-violet-300";
  const bgColor = isLeft ? "bg-amber-50" : "bg-violet-50";
  const badgeColor = isLeft ? "bg-amber-100 text-amber-800" : "bg-violet-100 text-violet-800";

  return (
    <article
      onClick={(e) => {
        if (editing) return;
        if (e.target.closest("button, input, textarea")) return;
        setExpanded((v) => !v);
      }}
      className={`group flex w-[220px] min-h-0 flex-col overflow-hidden rounded-xl border ${borderColor} ${BRANCH_CARD_MAX_H} ${editing ? "border-emerald-400 bg-white" : `${bgColor} cursor-pointer`} px-3 py-2 shadow-sm transition-colors`}
    >
      <div className="mb-1 flex shrink-0 items-center justify-between">
        <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${badgeColor}`}>支线</span>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleEdit();
            }}
            className={`rounded p-0.5 transition-colors ${editing ? "text-emerald-600 hover:bg-emerald-100" : "text-slate-500 hover:bg-slate-100 opacity-80 md:opacity-0 md:group-hover:opacity-100"}`}
            title={editing ? "完成编辑" : "编辑支线"}
          >
            {editing ? <Check className="h-3 w-3" /> : <PenLine className="h-3 w-3" />}
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="rounded p-0.5 text-slate-500 opacity-80 hover:bg-red-50 hover:text-red-500 md:opacity-0 md:group-hover:opacity-100"
            title="删除支线"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>
      <div
        className={`flex min-h-0 flex-1 flex-col ${isOpen ? "overflow-y-auto overflow-x-hidden" : "overflow-hidden"}`}
      >
        <EditableText
          value={branch.name}
          onSave={(val) => onUpdate("name", val)}
          className={`shrink-0 text-[11px] font-medium leading-4 text-slate-800 ${editing ? "" : isOpen ? "" : "line-clamp-2 break-words"}`}
          editable={editing}
        />
        <div className="mt-1 min-h-0 flex-1 text-[10px] leading-4 text-slate-600">
          {branch.summary ? (
            <EditableText
              value={branch.summary}
              onSave={(val) => onUpdate("summary", val)}
              className={`block break-words text-[10px] leading-4 text-slate-600 ${editing ? "whitespace-pre-wrap" : isOpen ? "" : "line-clamp-4"}`}
              multiline
              editable={editing}
            />
          ) : (
            <span
              className={`block break-words text-[10px] leading-4 ${editing ? "cursor-pointer rounded px-1 hover:bg-slate-100" : isOpen ? "text-slate-400" : "line-clamp-4 text-slate-400"}`}
            >
              {editing ? "点击添加支线摘要" : "（暂无支线摘要）"}
            </span>
          )}
        </div>
      </div>
      <p className="mt-1 shrink-0 text-[10px] text-slate-500">
        第{branch.chapter_start}-{branch.chapter_end}章
      </p>
    </article>
  );
}

/* ─────────────────────────── Outline Tree ─────────────────────────────── */

function InlineTree({ tree, pulseFocus, onUpdateNode, onDeleteNode, onAddBranch, onSelectNode }) {
  const timeline = useMemo(() => sortTimelineNodes(tree?.timeline || []), [tree?.timeline]);
  const branches = tree?.branches || [];
  const foreshadowing = tree?.foreshadowing || [];
  const isPulsing = (type, id) => pulseFocus?.type === type && String(pulseFocus?.id) === String(id);
  const nodeRefs = useRef(new Map());

  // Build a set of all valid node IDs (timeline + branch) for orphan detection
  const allNodeIds = useMemo(() => {
    const ids = new Set(timeline.map((t) => String(t.id)));
    branches.forEach((b) => ids.add(String(b.id)));
    return ids;
  }, [timeline, branches]);

  // Foreshadowing planted on a branch node
  const branchForeshadowing = useMemo(() => {
    const map = new Map();
    for (const f of foreshadowing) {
      if (f.plant_node && branches.some((b) => String(b.id) === String(f.plant_node))) {
        const key = String(f.plant_node);
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(f);
      }
    }
    return map;
  }, [foreshadowing, branches]);

  // Orphan foreshadowing: plant_node matches neither timeline nor branch
  const orphanForeshadowing = useMemo(() => {
    return foreshadowing.filter((f) => !f.plant_node || !allNodeIds.has(String(f.plant_node)));
  }, [foreshadowing, allNodeIds]);

  useEffect(() => {
    if (!pulseFocus?.id || !pulseFocus?.type) return;
    const key = `${pulseFocus.type}:${String(pulseFocus.id)}`;
    const el = nodeRefs.current.get(key);
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [pulseFocus]);

  if (!timeline.length) return <p className="text-sm text-slate-600">暂无大纲数据。</p>;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="ml-2 border-l-2 border-slate-200 pl-4">
        {timeline.map((node, idx) => {
          const nodeBranches = branches.filter((b) => b.attach_to === node.id);
          const planted = foreshadowing.filter((f) => f.plant_node === node.id);
          return (
            <div key={node.id || idx} className="relative mb-4">
              <div className="absolute -left-[18px] top-4 w-3 border-t-2 border-slate-200" />
              <article
                ref={(el) => {
                  const key = `timeline:${String(node.id)}`;
                  if (el) nodeRefs.current.set(key, el);
                  else nodeRefs.current.delete(key);
                }}
                className={`rounded-lg border border-blue-200 bg-blue-50 p-3 transition ${
                  isPulsing("timeline", node.id) ? "animate-pulse ring-2 ring-blue-300 ring-offset-1" : ""
                }`}
                onClick={() => onSelectNode?.({ type: "timeline", id: node.id })}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <h4 className="truncate text-sm font-semibold text-slate-800">
                    {node.id || `T${idx + 1}`} {node.development_node || "主线节点"}
                  </h4>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      className="rounded p-1 text-slate-500 hover:bg-blue-100"
                      title="新增支线"
                      onClick={(e) => {
                        e.stopPropagation();
                        onAddBranch(node.id, "right");
                      }}
                    >
                      <Plus className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      className="rounded p-1 text-slate-500 hover:bg-red-50 hover:text-red-500"
                      title="删除主线"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteNode(node.id);
                      }}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
                <p className="line-clamp-2 text-xs text-slate-600">{node.summary || "（暂无摘要）"}</p>
                <p className="mt-1 text-[11px] text-slate-500">
                  {node.time_node || "未设时间"} · 第{node.chapter_start}-{node.chapter_end}章
                </p>
              </article>

              {(nodeBranches.length > 0 || planted.length > 0) && (
                <div className="ml-4 mt-2 border-l border-slate-200 pl-3">
                  {nodeBranches.map((b, bIdx) => {
                    const branchPlanted = branchForeshadowing.get(String(b.id)) || [];
                    return (
                      <div
                        ref={(el) => {
                          const key = `branch:${String(b.id)}`;
                          if (el) nodeRefs.current.set(key, el);
                          else nodeRefs.current.delete(key);
                        }}
                        key={b.id || bIdx}
                        className={`relative mb-2 rounded-md border border-emerald-200 bg-emerald-50 p-2 transition ${
                          isPulsing("branch", b.id) ? "animate-pulse ring-2 ring-emerald-300 ring-offset-1" : ""
                        }`}
                        onClick={() => onSelectNode?.({ type: "branch", id: b.id })}
                      >
                        <div className="absolute -left-[13px] top-3 w-2 border-t border-slate-200" />
                        <div className="flex items-center justify-between gap-2">
                          <div className="truncate text-xs font-semibold text-slate-800">
                            {b.id || `B${bIdx + 1}`} {b.name || "支线"}
                          </div>
                          <button
                            type="button"
                            className="rounded p-0.5 text-slate-500 hover:bg-red-50 hover:text-red-500"
                            onClick={(e) => {
                              e.stopPropagation();
                              onDeleteNode(b.id);
                            }}
                            title="删除支线"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                        <p className="line-clamp-1 text-[11px] text-slate-600">{b.summary || "（暂无支线摘要）"}</p>
                        {branchPlanted.length > 0 && (
                          <div className="ml-2 mt-1 border-l border-emerald-300 pl-2">
                            {branchPlanted.map((f, fIdx) => (
                              <div
                                ref={(el) => {
                                  const key = `foreshadowing:${String(f.id)}`;
                                  if (el) nodeRefs.current.set(key, el);
                                  else nodeRefs.current.delete(key);
                                }}
                                key={f.id || fIdx}
                                className={`relative mb-1 rounded border border-amber-200 bg-amber-50 p-1.5 transition ${
                                  isPulsing("foreshadowing", f.id) ? "animate-pulse ring-2 ring-amber-300 ring-offset-1" : ""
                                }`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onSelectNode?.({ type: "foreshadowing", id: f.id });
                                }}
                              >
                                <div className="absolute -left-[9px] top-2.5 w-1.5 border-t border-slate-200" />
                                <div className="flex items-center justify-between gap-1">
                                  <div className="truncate text-[11px] font-semibold text-slate-800">
                                    {f.id || `F${fIdx + 1}`} 伏笔
                                  </div>
                                  <button
                                    type="button"
                                    className="rounded p-0.5 text-slate-400 hover:bg-red-50 hover:text-red-500"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onDeleteNode(f.id);
                                    }}
                                    title="删除伏笔"
                                  >
                                    <Trash2 className="h-2.5 w-2.5" />
                                  </button>
                                </div>
                                <p className="line-clamp-1 text-[10px] text-slate-600">{f.content || "（暂无伏笔内容）"}</p>
                                <p className="text-[9px] text-slate-500">回收：{f.payoff_node || "未设"}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {planted.map((f, fIdx) => (
                    <div
                      ref={(el) => {
                        const key = `foreshadowing:${String(f.id)}`;
                        if (el) nodeRefs.current.set(key, el);
                        else nodeRefs.current.delete(key);
                      }}
                      key={f.id || fIdx}
                      className={`relative mb-2 rounded-md border border-amber-200 bg-amber-50 p-2 transition ${
                        isPulsing("foreshadowing", f.id) ? "animate-pulse ring-2 ring-amber-300 ring-offset-1" : ""
                      }`}
                      onClick={() => onSelectNode?.({ type: "foreshadowing", id: f.id })}
                    >
                      <div className="absolute -left-[13px] top-3 w-2 border-t border-slate-200" />
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate text-xs font-semibold text-slate-800">
                          {f.id || `F${fIdx + 1}`} 伏笔
                        </div>
                        <button
                          type="button"
                          className="rounded p-0.5 text-slate-500 hover:bg-red-50 hover:text-red-500"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteNode(f.id);
                          }}
                          title="删除伏笔"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                      <p className="line-clamp-1 text-[11px] text-slate-600">{f.content || "（暂无伏笔内容）"}</p>
                      <p className="text-[10px] text-slate-500">回收：{f.payoff_node || "未设"}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {orphanForeshadowing.length > 0 && (
          <div className="mt-4 rounded-md border border-dashed border-amber-300 bg-amber-50/50 p-3">
            <p className="mb-2 text-xs font-semibold text-amber-700">未关联伏笔</p>
            {orphanForeshadowing.map((f, fIdx) => (
              <div
                ref={(el) => {
                  const key = `foreshadowing:${String(f.id)}`;
                  if (el) nodeRefs.current.set(key, el);
                  else nodeRefs.current.delete(key);
                }}
                key={f.id || fIdx}
                className={`relative mb-2 rounded border border-amber-200 bg-amber-50 p-2 transition ${
                  isPulsing("foreshadowing", f.id) ? "animate-pulse ring-2 ring-amber-300 ring-offset-1" : ""
                }`}
                onClick={() => onSelectNode?.({ type: "foreshadowing", id: f.id })}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="truncate text-xs font-semibold text-slate-800">
                    {f.id || `F${fIdx + 1}`} 伏笔
                  </div>
                  <button
                    type="button"
                    className="rounded p-0.5 text-slate-500 hover:bg-red-50 hover:text-red-500"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteNode(f.id);
                    }}
                    title="删除伏笔"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
                <p className="line-clamp-1 text-[11px] text-slate-600">{f.content || "（暂无伏笔内容）"}</p>
                <p className="text-[10px] text-amber-600">
                  埋设：{f.plant_node || "未设"} → 回收：{f.payoff_node || "未设"}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ─────────────────────────── Supervisor Chat Panel ──────────────────────── */

const mdComponents = {
  h1: ({ node, ...props }) => <h1 className="text-base font-bold text-slate-800 mt-3 mb-1.5" {...props} />,
  h2: ({ node, ...props }) => <h2 className="text-sm font-bold text-slate-800 mt-2.5 mb-1" {...props} />,
  h3: ({ node, ...props }) => <h3 className="text-sm font-semibold text-slate-700 mt-2 mb-0.5" {...props} />,
  ul: ({ node, ...props }) => <ul className="list-disc pl-5 my-1.5 space-y-0.5" {...props} />,
  ol: ({ node, ...props }) => <ol className="list-decimal pl-5 my-1.5 space-y-0.5" {...props} />,
  li: ({ node, ...props }) => <li className="text-sm" {...props} />,
  p: ({ node, ...props }) => <p className="my-1.5" {...props} />,
  strong: ({ node, ...props }) => <strong className="font-semibold text-slate-800" {...props} />,
  code: ({ node, inline, ...props }) =>
    inline ? (
      <code className="rounded bg-slate-100 px-1 py-0.5 text-xs text-violet-700" {...props} />
    ) : (
      <code className="block rounded bg-slate-50 p-2.5 text-xs text-slate-600 overflow-x-auto my-2" {...props} />
    ),
};

function formatOutlineProgress(d) {
  if (!d?.section || !d?.node) return "";
  const n = d.node;
  if (d.section === "story") return `📘 作品：${n.title || "未命名"}｜${n.genre || "未分类"}｜${n.volume || ""}\n`;
  if (d.section === "timeline") return `🧭 主线：${n.development_node || ""}｜${n.summary || n.time_node || ""}\n`;
  if (d.section === "branches") return `🌿 支线：${n.name || ""} - ${n.summary || ""}\n`;
  if (d.section === "foreshadowing") return `🪝 伏笔：${n.content || ""}\n`;
  return "";
}

/** 执行过程一步：独立气泡 + 可选小流式区（结束后收起） */
function SupervisorChatPanel({ workId, onOutlineUpdated, onChapterUpdated, onCharactersUpdated, onChapterIntelUpdate }) {
  const [timeline, setTimeline] = useState([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const activeSessionIdRef = useRef(null);
  /** 当前正在流式累加的文字，冻结后变为 timeline 中的 assistant 气泡 */
  const [assistantDraft, setAssistantDraft] = useState("");
  const timelineIdRef = useRef(0);
  const [editDiff, setEditDiff] = useState(null); // { diff, summary, new_content, chapter_number, readonly }
  const [outlineDiff, setOutlineDiff] = useState(null); // { diff, summary, message, operations }
  const [characterDiff, setCharacterDiff] = useState(null); // { diff, summary }
  const [confirming, setConfirming] = useState(false);
  const bottomRef = useRef(null);
  const sseRef = useRef(null);
  const assistantDraftRef = useRef("");
  const lastOutlinePhaseRef = useRef("");

  // 会话列表
  const [sessions, setSessions] = useState([]);
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const dropdownRef = useRef(null);

  const syncSessionId = (id) => {
    activeSessionIdRef.current = id;
    setSessionId(id);
  };

  // 加载会话列表
  const loadSessions = async () => {
    try {
      const list = await sessionApi.listSupervisor(workId);
      setSessions(list || []);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    if (workId) loadSessions();
  }, [workId]);

  // 点击外部关闭下拉
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setSessionListOpen(false);
      }
    };
    if (sessionListOpen) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [sessionListOpen]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [timeline, assistantDraft, editDiff, outlineDiff, characterDiff, running]);

  const pushExecStep = (label, { panelOpen = true } = {}) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => {
      const updated = prev.map((item) =>
        item.kind === "step" && item.status === "running"
          ? { ...item, status: "done", panelOpen: false }
          : item
      );
      return [...updated, { kind: "step", id, label, status: "running", stream: "", panelOpen, timestamp: Date.now() }];
    });
  };

  const pushExecStepDone = (label) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => {
      const updated = prev.map((item) =>
        item.kind === "step" && item.status === "running"
          ? { ...item, status: "done", panelOpen: false }
          : item
      );
      return [...updated, { kind: "step", id, label, status: "done", stream: "", panelOpen: false, timestamp: Date.now() }];
    });
  };

  const appendLastRunningStream = (chunk) => {
    if (chunk == null || chunk === "") return;
    setTimeline((prev) => {
      let i = prev.findLastIndex((item) => item.kind === "step" && item.status === "running");
      let base = prev;
      if (i < 0) {
        const id = ++timelineIdRef.current;
        base = [...prev, { kind: "step", id, label: "进行中", status: "running", stream: "", panelOpen: true, timestamp: Date.now() }];
        i = base.length - 1;
      }
      const next = [...base];
      next[i] = { ...next[i], stream: next[i].stream + chunk, panelOpen: true };
      return next;
    });
  };

  const finalizeLastRunningStep = () => {
    setTimeline((prev) => {
      const i = prev.findLastIndex((item) => item.kind === "step" && item.status === "running");
      if (i < 0) return prev;
      const next = [...prev];
      next[i] = { ...next[i], status: "done", panelOpen: false };
      return next;
    });
  };

  const toggleStepPanel = (id) => {
    setTimeline((prev) => {
      const i = prev.findIndex((item) => item.kind === "step" && item.id === id);
      if (i < 0) return prev;
      const next = [...prev];
      next[i] = { ...next[i], panelOpen: !next[i].panelOpen };
      return next;
    });
  };

  const addMessage = (role, content, meta = {}) => {
    const id = ++timelineIdRef.current;
    setTimeline((prev) => [...prev, { kind: "message", id, role, content, ...meta, timestamp: Date.now() }]);
  };

  // 冻结当前 assistantDraft 为一个独立的 assistant 气泡
  const freezeDraft = () => {
    const draft = assistantDraftRef.current;
    if (draft && draft.trim()) {
      const id = ++timelineIdRef.current;
      setTimeline((prev) => [...prev, { kind: "message", id, role: "assistant", content: draft, timestamp: Date.now() }]);
    }
    setAssistantDraft("");
    assistantDraftRef.current = "";
  };

  // 选择已有会话
  const handleSelectSession = async (session) => {
    if (running) return;
    // 重置状态
    setTimeline([]);
    setInput("");
    setAssistantDraft("");
    setEditDiff(null);
    setOutlineDiff(null);
    setCharacterDiff(null);
    setConfirming(false);
    timelineIdRef.current = 0;

    syncSessionId(session.id);
    setSessionListOpen(false);

    try {
      const msgs = await sessionApi.getSupervisorMessages(session.id);
      if (msgs && msgs.length > 0) {
        const loaded = msgs
          .filter((m) => ["user", "assistant", "tool_call", "tool_result"].includes(m.role))
          .map((m) => {
            const id = ++timelineIdRef.current;
            const ts = m.created_at ? new Date(m.created_at).getTime() : Date.now();
            if (m.role === "tool_call") {
              return {
                kind: "message",
                id,
                role: "assistant",
                content: `调用工具: ${m.content || "unknown"}`,
                type: "agent_phase",
                title: "工具调用",
                meta: m.meta || {},
                timestamp: ts,
              };
            }
            if (m.role === "tool_result") {
              return {
                kind: "message",
                id,
                role: "assistant",
                content: m.content || "",
                type: "agent_phase",
                title: `工具结果${m.meta?.tool_name ? ` · ${m.meta.tool_name}` : ""}`,
                meta: m.meta || {},
                timestamp: ts,
              };
            }

            const isProcess = m.meta?.type === "process_note" || (m.meta?.type === "agent_phase" && ["stage_start", "evaluation_done"].includes(m.meta?.event));
            if (m.role === "assistant" && isProcess) {
              return {
                kind: "step",
                id,
                label: m.content || m.meta?.label || "处理中",
                status: "done",
                stream: "",
                panelOpen: false,
                timestamp: ts,
              };
            }

            if (
              m.role === "assistant"
              && m.meta?.intent === "requirements_planner"
              && m.meta?.requirements_plan
            ) {
              return {
                kind: "message",
                id,
                role: "assistant",
                content: "",
                type: "requirements_todolist",
                todoCard: m.meta.requirements_plan,
                meta: m.meta || {},
                timestamp: ts,
              };
            }

            return {
              kind: "message",
              id,
              role: m.role,
              content: m.content,
              type: m.meta?.type,
              title: m.meta?.title,
              diffCard: m.meta?.diffCard,
              outlineDiffCard: m.meta?.outlineDiffCard,
              characterDiffCard: m.meta?.characterDiffCard,
              chapterMetaCard: m.meta?.chapterMetaCard,
              consistencyReportCard: m.meta?.consistencyReportCard,
              meta: m.meta || {},
              timestamp: ts,
            };
          });
        setTimeline(loaded);
      }
    } catch {
      // ignore
    }
  };

  // 新建会话
  const handleNewSession = () => {
    if (running) return;
    setTimeline([]);
    setInput("");
    syncSessionId(null);
    setAssistantDraft("");
    setEditDiff(null);
    setOutlineDiff(null);
    setCharacterDiff(null);
    setConfirming(false);
    timelineIdRef.current = 0;
    setSessionListOpen(false);
  };

  // 删除会话
  const handleDeleteSession = async (id) => {
    if (running) return;
    if (!confirm("确定删除这个对话？")) return;
    try {
      await sessionApi.deleteSupervisor(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (sessionId === id) {
        handleNewSession();
      }
    } catch {
      // ignore
    }
  };

  // 当前会话标题
  const currentSessionTitle = useMemo(() => {
    if (!sessionId) return "新对话";
    const s = sessions.find((s) => s.id === sessionId);
    return s?.title || "新对话";
  }, [sessionId, sessions]);

  const connectSSE = (url, body) => {
    setRunning(true);
    setAssistantDraft("");
    timelineIdRef.current = 0;

    const ctl = new AbortController();
    authFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          let msg = `HTTP ${res.status}`;
          try { const e = await res.json(); msg = e.detail || e.message || msg; } catch { /* ignore */ }
          setRunning(false);
          addMessage("system", `错误: ${msg}`, { type: "error" });
          return;
        }
        if (!res.body) { setRunning(false); return; }
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        let ev = "";
        (async () => {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const lines = buf.split("\n");
            buf = lines.pop() || "";
            for (const ln of lines) {
              if (ln.startsWith("event: ")) ev = ln.slice(7).trim();
              else if (ln.startsWith("data: ")) {
                try { onSSE(ev, JSON.parse(ln.slice(6))); } catch { /* ignore */ }
              }
            }
          }
          setRunning(false);
        })().catch(() => setRunning(false));
      })
      .catch((e) => {
        setRunning(false);
        if (e?.name !== "AbortError") addMessage("system", `网络错误: ${e?.message || "无法连接"}`, { type: "error" });
      });
    sseRef.current = { close: () => ctl.abort() };
  };

  const onSSE = (ev, d) => {
    switch (ev) {
      case "session_created":
        syncSessionId(d.session_id);
        loadSessions();
        break;
      case "tool_calls": {
        // 冻结当前 draft 为独立气泡
        freezeDraft();
        const label = `调用工具: ${(d.tools || []).join(", ") || "unknown"}`;
        const id = ++timelineIdRef.current;
        setTimeline((prev) => {
          const updated = prev.map((item) =>
            item.kind === "step" && item.status === "running"
              ? { ...item, status: "done", panelOpen: false }
              : item
          );
          return [...updated, { kind: "step", id, label, status: "done", stream: "", panelOpen: false, timestamp: Date.now() }];
        });
        break;
      }
      case "tool_result":
        break;
      case "tool_executed":
        break;
      case "supervisor_stream":
        setAssistantDraft((p) => {
          const next = p + d.chunk;
          assistantDraftRef.current = next;
          return next;
        });
        break;
      case "supervisor_done": {
        finalizeLastRunningStep();
        freezeDraft();
        setRunning(false);
        break;
      }
      case "stage_start": {
        const label = d.label || d.stage || "进行中";
        // 如果是新的 thinking/tool_calling 阶段，先冻结当前 draft
        if (d.stage === "thinking" || d.stage === "tool_calling") {
          freezeDraft();
        }
        pushExecStep(label);
        break;
      }
      case "outline_stream":
        break;
      case "outline_status":
        if (d?.phase && d.phase !== lastOutlinePhaseRef.current) {
          finalizeLastRunningStep();
          pushExecStep(d?.message || d.phase);
          lastOutlinePhaseRef.current = d.phase;
        } else if (d?.message) {
          appendLastRunningStream(`${d.message}\n`);
        }
        break;
      case "outline_tree_progress": {
        const line = formatOutlineProgress(d);
        if (line) appendLastRunningStream(line);
        break;
      }
      case "outline_done": {
        finalizeLastRunningStep();
        lastOutlinePhaseRef.current = "";
        if (d.work_id && onOutlineUpdated) {
          authFetch(`${API_BASE}/works/${d.work_id}`)
            .then((r) => r.json())
            .then((w) => {
              if (w.outline_tree) onOutlineUpdated(w.outline_tree);
            })
            .catch(() => {});
        }
        addMessage("assistant", `已创建作品「${d.title}」的大纲。`, { type: "outline_created" });
        break;
      }
      case "outline_edit_done":
        finalizeLastRunningStep();
        addMessage("assistant", d.message || "大纲已编辑。", { type: "outline_edited" });
        if (workId) {
          authFetch(`${API_BASE}/works/${workId}`)
            .then((r) => r.json())
            .then((w) => {
              if (w.outline_tree) onOutlineUpdated(w.outline_tree);
            })
            .catch(() => {});
        }
        break;
      case "plan_stream":
      case "thinking_stream":
      case "write_stream":
      case "edit_chapter_stream":
        appendLastRunningStream(d.chunk);
        break;
      case "plan_done":
        finalizeLastRunningStep();
        break;
      case "thinking_done":
        finalizeLastRunningStep();
        break;
      case "saved":
        finalizeLastRunningStep();
        addMessage("assistant", `第${d.chapter_number}章「${d.title}」已保存，共 ${d.word_count} 字。`, { type: "chapter_saved" });
        if (onChapterUpdated) onChapterUpdated(d.chapter_number);
        break;
      case "write_done":
        finalizeLastRunningStep();
        break;
      case "evaluation_done":
        finalizeLastRunningStep();
        pushExecStepDone(
          `章节评估完成：编辑 ${d.editor?.total_score ?? "-"} /60，读者 ${d.reader?.total_score ?? "-"} /60`
        );
        break;
      case "todolist_generated": {
        const result = handleTodolistGenerated(d);
        finalizeLastRunningStep();
        addMessage(result.addMessage.role, result.addMessage.content, result.addMessage.meta);
        break;
      }
      case "outline_edit_diff": {
        const result = handleOutlineEditDiff(d);
        finalizeLastRunningStep();
        setOutlineDiff(result.setOutlineDiff);
        addMessage(result.addMessage.role, result.addMessage.content, result.addMessage.meta);
        break;
      }
      case "character_edit_diff": {
        const result = handleCharacterEditDiff(d);
        setCharacterDiff({ diff: d.diff, summary: d.summary, readonly: !!d.readonly });
        addMessage(result.addMessage.role, result.addMessage.content, result.addMessage.meta);
        break;
      }
      case "edit_chapter_diff":
        finalizeLastRunningStep();
        {
        const card = {
          diff: d.diff,
          summary: d.summary,
          new_content: d.new_content,
          chapter_number: d.chapter_number,
          readonly: false,
        };
        setEditDiff(card);
        addMessage("assistant", "", { type: "edit_diff_card", diffCard: card });
        }
        break;
      case "edit_chapter_auto_applied":
        finalizeLastRunningStep();
        {
        const card = {
          diff: d.diff,
          summary: d.summary,
          chapter_number: d.chapter_number,
          readonly: true,
        };
        setEditDiff(null);
        addMessage("assistant", "", { type: "edit_diff_card", diffCard: card });
        }
        setRunning(false);
        {
        const title = d?.title || `第${d.chapter_number}章`;
        const wordCount = Number.isFinite(d?.word_count) ? d.word_count : "未知";
        addMessage("assistant", `第${d.chapter_number}章「${title}」已自动优化并保存，共 ${wordCount} 字。`, { type: "chapter_edited" });
        }
        if (onChapterUpdated) onChapterUpdated(d.chapter_number);
        break;
      case "edit_chapter_accepted":
        setEditDiff(null);
        setRunning(false);
        addMessage("assistant", `第${d.chapter_number}章「${d.title}」修改已保存，共 ${d.word_count} 字。`, { type: "chapter_edited" });
        if (onChapterUpdated) onChapterUpdated(d.chapter_number);
        break;
      case "error":
        finalizeLastRunningStep();
        setAssistantDraft("");
        addMessage("system", `错误: ${d.message}`, { type: "error" });
        setRunning(false);
        break;
      case "characters_updated":
        if (d?.message) pushExecStepDone(d.message);
        if (onCharactersUpdated) onCharactersUpdated();
        break;
      case "chapter_metadata_generated":
        onChapterIntelUpdate?.(d.chapter_number, {
          chapter_number: d.chapter_number,
          summary: d.summary,
          key_plot_points: d.key_plot_points || [],
          outline_links: d.outline_links || [],
          involved_characters: d.involved_characters || [],
          foreshadows: d.foreshadows || [],
          facts: d.facts || [],
          updated_at: d.updated_at,
        });
        addMessage("assistant", "", {
          type: "chapter_meta_card",
          chapterMetaCard: {
            chapter_number: d.chapter_number,
            summary: d.summary,
            key_plot_points: d.key_plot_points || [],
            foreshadows: d.foreshadows || [],
          },
        });
        break;
      case "query_result":
        pushExecStepDone(`查询 ${d.source || "资料"}: ${String(d.summary || "").slice(0, 100)}`);
        break;
      case "title_proposed":
        if (d?.title) pushExecStepDone(`拟定标题: ${d.title}`);
        break;
      default:
        break;
    }
  };

  const handleSend = () => {
    if (running || !input.trim()) return;
    const msg = input.trim();
    addMessage("user", msg);
    setInput("");

    const sid = activeSessionIdRef.current;
    if (!sid) {
      connectSSE(`${API_BASE}/supervisor/start`, { message: msg, work_id: workId, auto_mode: true });
    } else {
      connectSSE(`${API_BASE}/supervisor/resume`, { session_id: sid, message: msg });
    }
  };

  const handleConfirmEdit = async (accept, targetDiff = null) => {
    const diffTarget = targetDiff || editDiff;
    if (!diffTarget || !sessionId || confirming) return;
    setConfirming(true);
    try {
      const body = { session_id: sessionId, action: accept ? "accept" : "reject" };
      if (accept && diffTarget.new_content) body.new_content = diffTarget.new_content;
      const res = await authFetch(`${API_BASE}/supervisor/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }
      if (data.error) {
        throw new Error(data.error);
      }
      if (!accept) {
        setEditDiff(null);
        setRunning(false);
        addMessage("assistant", "已拒绝修改。");
      } else {
        setEditDiff(null);
        setRunning(false);
        const ch = data.chapter_number;
        if (ch && onChapterUpdated) onChapterUpdated(ch);
        addMessage("assistant", data.status === "accepted" ? `第${ch || diffTarget.chapter_number}章修改已保存。` : "操作完成。");
      }
    } catch (err) {
      addMessage("system", `确认失败: ${err.message}`, { type: "error" });
    } finally {
      setConfirming(false);
    }
  };

  const handleConfirmOutline = async (action) => {
    if (!sessionId || (!outlineDiff && !characterDiff) || confirming) return;
    setConfirming(true);
    try {
      const res = await authFetch(`${API_BASE}/supervisor/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, action }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      }
      if (data.error) {
        throw new Error(data.error);
      }
      if (data.status === "accepted") {
        setOutlineDiff(null);
        setCharacterDiff(null);
        setRunning(false);
        addMessage("assistant", "大纲和角色修改已保存。", { type: "outline_edited" });
        if (workId) {
          authFetch(`${API_BASE}/works/${workId}`)
            .then((r) => r.json())
            .then((w) => {
              if (w.outline_tree) onOutlineUpdated(w.outline_tree);
            })
            .catch(() => {});
        }
      } else {
        setOutlineDiff(null);
        setCharacterDiff(null);
        setRunning(false);
        addMessage("assistant", "大纲和角色修改已取消，保持原样。", { type: "edit_cancelled" });
      }
    } catch (err) {
      addMessage("system", `确认失败: ${err.message}`, { type: "error" });
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* 会话选择器 */}
      <div ref={dropdownRef} className="relative flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div className="flex min-w-0 max-w-[220px] flex-1 items-center gap-1">
          <button
            type="button"
            onClick={() => !running && setSessionListOpen(!sessionListOpen)}
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-50"
            disabled={running}
          >
            <span className="truncate">{currentSessionTitle}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          </button>
        </div>
        <button
          type="button"
          onClick={handleNewSession}
          disabled={running}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-500 disabled:opacity-50"
          title="新建对话"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        {/* 下拉列表 */}
        {sessionListOpen && (
          <div className="absolute left-3 top-full z-50 w-[220px] max-h-[280px] overflow-y-auto rounded-b-lg border border-t-0 border-slate-200 bg-white shadow-lg">
            {sessions.length === 0 ? (
              <p className="px-3 py-3 text-center text-xs text-slate-400">暂无对话</p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleSelectSession(s)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") handleSelectSession(s);
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
                    s.id === sessionId
                      ? "bg-blue-50 text-blue-700"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate">{s.title || "新对话"}</span>
                  {s.updated_at && (
                    <span className="shrink-0 text-[10px] text-slate-400">
                      {new Date(s.updated_at).toLocaleDateString("zh-CN", { month: "short", day: "numeric" })}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteSession(s.id);
                    }}
                    disabled={running}
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 disabled:opacity-50"
                    title="删除对话"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div className="space-y-3">
          {timeline.map((item) => {
            if (item.kind === "step") {
              const showContent = item.status === "running" || (item.status === "done" && item.panelOpen);
              return (
                <div key={`s-${item.id}`} className="flex gap-2 justify-start pl-1">
                  <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-slate-300">
                    {item.status === "running" ? (
                      <Loader2 className="h-3 w-3 animate-spin text-slate-400" />
                    ) : (
                      <Check className="h-3 w-3 text-slate-300" />
                    )}
                  </div>
                  <div className="max-w-[min(100%,42rem)] flex-1 min-w-0 py-0.5">
                    <div
                      className={`text-[11px] font-normal leading-snug text-slate-400 select-none ${item.stream && item.stream.trim() ? "cursor-pointer hover:text-slate-600" : ""}`}
                      onClick={() => item.stream && item.stream.trim() && toggleStepPanel(item.id)}
                    >
                      {item.label}
                    </div>
                    {showContent && item.stream && item.stream.trim().length > 0 && (
                      <div
                        ref={(el) => {
                          if (el && item.status === "running") {
                            el.scrollTop = el.scrollHeight;
                          }
                        }}
                        className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-[10px] font-normal leading-relaxed text-slate-400/90"
                      >
                        {item.stream}
                        {item.status === "running" && (
                          <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom" />
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            }

            // kind === "message"
            const msg = item;
            return (
              <div key={`m-${item.id}`} className={`flex gap-2 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role !== "user" && (
                  <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                    msg.type === "error" ? "bg-red-100 text-red-500" : "bg-blue-100 text-blue-500"
                  }`}>
                    {msg.type === "error" ? "!" : <Bot className="h-3 w-3" />}
                  </div>
                )}
                <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-blue-600 text-white"
                    : msg.type === "error"
                      ? "bg-red-50 text-red-700 border border-red-200"
                      : msg.type === "agent_phase"
                        ? "bg-slate-50 text-slate-800 border border-slate-200"
                        : "bg-slate-100 text-slate-800"
                }`}>
                  {msg.type === "edit_diff_card" ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-slate-700">
                          第{msg.diffCard?.chapter_number}章修改建议
                          <span className="ml-2 text-xs text-slate-400">
                            +{msg.diffCard?.summary?.lines_added ?? 0}行 / -{msg.diffCard?.summary?.lines_removed ?? 0}行
                          </span>
                        </span>
                      </div>
                      <DiffViewer diff={msg.diffCard?.diff ?? []} summary={msg.diffCard?.summary ?? {}} collapsed />
                      {msg.diffCard?.readonly ? (
                        <div className="text-xs text-slate-500">
                          已自动应用并保存，无需确认。
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 justify-end">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2.5 text-xs text-slate-500 hover:text-red-600 hover:bg-red-50"
                            disabled={confirming}
                            onClick={() => handleConfirmEdit(false, msg.diffCard)}
                          >
                            <X className="mr-1 h-3 w-3" /> 拒绝
                          </Button>
                          <Button
                            size="sm"
                            className="h-7 px-2.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white gap-1"
                            disabled={confirming}
                            onClick={() => handleConfirmEdit(true, msg.diffCard)}
                          >
                            <Check className="h-3 w-3" /> 接受
                          </Button>
                        </div>
                      )}
                    </div>
                  ) : msg.type === "requirements_todolist" ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-medium text-slate-700">需求任务清单</p>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] ${
                            msg.todoCard?.ready_to_execute
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-amber-100 text-amber-700"
                          }`}
                        >
                          {msg.todoCard?.ready_to_execute ? "可执行" : "待澄清"}
                        </span>
                      </div>
                      {msg.todoCard?.intent_summary && (
                        <p className="text-xs text-slate-600">
                          目标：{msg.todoCard.intent_summary}
                        </p>
                      )}
                      {(msg.todoCard?.todolist || []).length > 0 ? (
                        <div className="space-y-2">
                          {(msg.todoCard.todolist || []).map((t, idx) => (
                            <div key={`${t.id || "T"}-${idx}`} className="rounded-lg border border-slate-200 bg-white p-2.5">
                              <div className="flex items-center gap-2 text-xs">
                                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{t.id || `T${idx + 1}`}</span>
                                <span className="font-medium text-slate-700">{t.task || "未命名任务"}</span>
                              </div>
                              <div className="mt-1 space-y-1 text-[11px] text-slate-500">
                                <p>负责人：{t.owner || "supervisor"}</p>
                                <p>状态：{t.status || "pending"}</p>
                                {Array.isArray(t.depends_on) && t.depends_on.length > 0 && (
                                  <p>依赖：{t.depends_on.join(", ")}</p>
                                )}
                                {t.done_criteria && <p>验收：{t.done_criteria}</p>}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500">暂无任务项。</p>
                      )}
                    </div>
                  ) : msg.type === "outline_diff_card" ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-slate-700">
                          大纲变更建议
                          <span className="ml-2 text-xs text-slate-400">
                            +{msg.outlineDiffCard?.summary?.total_added ?? 0} / ~{msg.outlineDiffCard?.summary?.total_modified ?? 0} / -{msg.outlineDiffCard?.summary?.total_removed ?? 0}
                          </span>
                        </p>
                      </div>
                      <OutlineDiffViewer diff={msg.outlineDiffCard?.diff ?? {}} summary={msg.outlineDiffCard?.summary ?? {}} collapsed />
                      {msg.outlineDiffCard?.readonly ? (
                        <div className="text-xs text-slate-500">
                          已自动应用并保存，无需确认。
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 justify-end">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2.5 text-xs text-slate-500 hover:text-red-600 hover:bg-red-50"
                            disabled={confirming}
                            onClick={() => handleConfirmOutline("reject")}
                          >
                            <X className="mr-1 h-3 w-3" /> 拒绝
                          </Button>
                          <Button
                            size="sm"
                            className="h-7 px-2.5 text-xs bg-emerald-600 hover:bg-emerald-700 text-white gap-1"
                            disabled={confirming}
                            onClick={() => handleConfirmOutline("accept")}
                          >
                            <Check className="h-3 w-3" /> 接受
                          </Button>
                        </div>
                      )}
                    </div>
                  ) : msg.type === "character_diff_card" ? (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-sm text-slate-700">
                          角色变更建议
                          <span className="ml-2 text-xs text-slate-400">
                            +{msg.characterDiffCard?.summary?.total_added ?? 0} / ~{msg.characterDiffCard?.summary?.total_modified ?? 0} / -{msg.characterDiffCard?.summary?.total_removed ?? 0}
                          </span>
                        </p>
                      </div>
                      <CharacterDiffViewer diff={msg.characterDiffCard?.diff ?? {}} summary={msg.characterDiffCard?.summary ?? {}} collapsed />
                    </div>
                  ) : msg.type === "chapter_meta_card" ? (
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-slate-700">章节结构元数据（第{msg.chapterMetaCard?.chapter_number}章）</p>
                      <p className="text-xs text-slate-600 whitespace-pre-wrap">{msg.chapterMetaCard?.summary || "无摘要"}</p>
                      <div className="text-xs text-slate-600">
                        <p className="font-medium text-slate-700">关键剧情点</p>
                        {(msg.chapterMetaCard?.key_plot_points || []).length > 0 ? (
                          <ul className="list-disc pl-4">
                            {(msg.chapterMetaCard?.key_plot_points || []).map((p, idx) => <li key={`kp-${idx}`}>{p}</li>)}
                          </ul>
                        ) : (
                          <p>无</p>
                        )}
                      </div>
                    </div>
                  ) : msg.type === "consistency_report_card" ? (
                    <div className="space-y-1">
                      <p className="text-sm font-medium text-slate-700">一致性检查（第{msg.consistencyReportCard?.chapter_number}章）</p>
                      <p className="text-xs text-slate-600">状态：{msg.consistencyReportCard?.consistency_status || "aligned"}</p>
                      <p className="text-xs text-slate-600">决策：{msg.consistencyReportCard?.decision || "none"}</p>
                      <p className="text-xs text-slate-600 whitespace-pre-wrap">{msg.consistencyReportCard?.reason || ""}</p>
                    </div>
                  ) : msg.role === "user" ? (
                    <p>{msg.content}</p>
                  ) : (
                    <>
                      {msg.type === "agent_phase" && msg.title && (
                        <div className="mb-1.5 flex items-center gap-1.5 border-b border-slate-200/80 pb-1 text-xs font-medium text-slate-500">
                          <PenLine className="h-3 w-3 shrink-0 text-violet-500" />
                          {msg.title}
                        </div>
                      )}
                      <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{msg.content}</Markdown>
                    </>
                  )}
                </div>
              </div>
            );
          })}
          {assistantDraft && (
            <div className="flex gap-2 justify-start">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500">
                <Bot className="h-3 w-3" />
              </div>
              <div className="max-w-[85%] rounded-xl bg-slate-100 px-3 py-2 text-sm leading-relaxed text-slate-800">
                <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>{assistantDraft}</Markdown>
                {running && (
                  <span className="inline-block h-2.5 w-px animate-pulse bg-slate-400 align-text-bottom ml-0.5" />
                )}
              </div>
            </div>
          )}
          {running && !timeline.some((item) => item.kind === "step" && item.status === "running") && !editDiff && !outlineDiff && !characterDiff && (
            <div className="flex gap-2 justify-start">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500 animate-pulse">
                <Bot className="h-3 w-3" />
              </div>
              <div className="rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-500">思考中...</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
      <div className="shrink-0 px-4 py-3">
        <div className="flex items-end gap-2 pr-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入指令... (如「修改大纲」「写第1章」「修改第1章的...」)"
            className="min-h-[40px] max-h-[120px] resize-none text-sm"
            rows={1}
            disabled={running}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
          />
          <Button
            size="icon"
            className="h-10 w-10 shrink-0 rounded-full"
            onClick={handleSend}
            disabled={!input.trim() || running}
            aria-label="发送消息"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}

function statusBadge(status) {
  switch (status) {
    case "草稿":
      return "bg-green-100 text-green-700";
    case "已保存":
      return "bg-blue-100 text-blue-700";
    default:
      return "bg-slate-100 text-slate-500";
  }
}

function normalizeChapterIntel(prev = {}, patch = {}) {
  return {
    chapter_number: patch.chapter_number ?? prev.chapter_number ?? null,
    summary: patch.summary ?? prev.summary ?? "",
    key_plot_points: Array.isArray(patch.key_plot_points) ? patch.key_plot_points : (prev.key_plot_points || []),
    outline_links: Array.isArray(patch.outline_links) ? patch.outline_links : (prev.outline_links || []),
    involved_characters: Array.isArray(patch.involved_characters) ? patch.involved_characters : (prev.involved_characters || []),
    foreshadows: Array.isArray(patch.foreshadows) ? patch.foreshadows : (prev.foreshadows || []),
    facts: Array.isArray(patch.facts) ? patch.facts : (prev.facts || []),
    updated_at: patch.updated_at ? new Date(patch.updated_at).getTime() : Date.now(),
  };
}

function ChapterIntelSidebar({ chapterNumber, intel, outlineTree, characters }) {
  if (!chapterNumber) return null;
  const timeText = intel?.updated_at ? new Date(intel.updated_at).toLocaleString("zh-CN", { hour12: false }) : "尚无更新";

  return (
    <aside className="rounded-[14px] border border-slate-300 bg-white p-3 shadow-[0_6px_20px_rgba(31,42,55,0.06)]">
      <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Chapter Intelligence</p>

      <section className="mb-2 rounded-xl border border-slate-200 bg-white p-3">
        <h4 className="text-sm font-semibold text-slate-800">章节元数据</h4>
        <p className="mt-1 text-xs text-slate-600 whitespace-pre-wrap">{intel?.summary || "暂无摘要"}</p>
        <div className="mt-2 text-xs text-slate-600">
          <p className="font-medium text-slate-700">关键剧情点</p>
          {(intel?.key_plot_points || []).length > 0 ? (
            <ul className="list-disc pl-4">
              {(intel?.key_plot_points || []).slice(0, 6).map((p, idx) => <li key={`kp-${idx}`}>{p}</li>)}
            </ul>
          ) : (
            <p>无</p>
          )}
        </div>
      </section>

      <section className="mb-2 rounded-xl border border-slate-200 bg-white p-3">
        <h4 className="text-sm font-semibold text-slate-800">大纲关联关系</h4>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(intel?.outline_links || []).slice(0, 6).map((n, idx) => (
            <span key={`tm-${idx}`} className="rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] font-semibold text-blue-700">
              {(n.type === "branch" ? "支线" : "主线")}·{n.id || "节点"}
            </span>
          ))}
          {(intel?.involved_characters || []).slice(0, 6).map((c, idx) => (
            <span key={`ch-${idx}`} className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
              角色·{c.name || "未知"}
            </span>
          ))}
          {(intel?.outline_links || []).length === 0 && (intel?.involved_characters || []).length === 0 && (
            <span className="text-xs text-slate-500">暂无可识别关联</span>
          )}
        </div>
      </section>

      <section className="mb-2 rounded-xl border border-slate-200 bg-white p-3">
        <h4 className="text-sm font-semibold text-slate-800">伏笔与事实索引</h4>
        <p className="mt-1 text-xs font-medium text-slate-700">伏笔</p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {(intel?.foreshadows || []).length > 0 ? (
            (intel.foreshadows || []).slice(0, 6).map((f, idx) => (
              <span key={`fa-${idx}`} className="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-[11px] font-semibold text-violet-700">
                {f.content || "伏笔"}
              </span>
            ))
          ) : (
            <span className="text-xs text-slate-500">无</span>
          )}
        </div>
        <p className="mt-2 text-xs font-medium text-slate-700">设定事实</p>
        <ul className="mt-1 list-disc pl-4 text-xs text-slate-600">
          {(intel?.facts || []).length > 0 ? (
            (intel.facts || []).slice(0, 4).map((f, idx) => <li key={`fh-${idx}`}>{f.key || "事实"}: {f.value || ""}</li>)
          ) : (
            <li>无</li>
          )}
        </ul>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-3">
        <h4 className="text-sm font-semibold text-slate-800">更新时间</h4>
        <p className="mt-1 text-xs text-slate-500">更新时间：{timeText}</p>
      </section>
    </aside>
  );
}

/* ─────────────────────────── Main Page ────────────────────────────────── */

export function WorkDetailPage() {
  const { workId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();

  const [work, setWork] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [characters, setCharacters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [outlineTree, setOutlineTree] = useState(null);
  const [graphFocus, setGraphFocus] = useState(null);
  const [treePulseFocus, setTreePulseFocus] = useState(null);
  const [saving, setSaving] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [chatPanelWidth, setChatPanelWidth] = useState(440);
  const [chatResizing, setChatResizing] = useState(false);

  const [titleDraft, setTitleDraft] = useState("");
  const [contentDraft, setContentDraft] = useState("");
  const [selectedChapter, setSelectedChapter] = useState(null);
  const [savingChapter, setSavingChapter] = useState(false);
  const [evaluatingChapter, setEvaluatingChapter] = useState(false);
  const [evaluationResult, setEvaluationResult] = useState(null);
  const [evaluationError, setEvaluationError] = useState("");
  const [selectedCharacter, setSelectedCharacter] = useState(null);
  const [chapterIntelByNumber, setChapterIntelByNumber] = useState({});
  const chapterTextareaRef = useRef(null);
  const resizeStartRef = useRef({ x: 0, width: 440 });
  const treePulseTimerRef = useRef(null);

  const mainTab = searchParams.get("tab") === "chapter" ? "chapter" : "outline";
  const chRaw = searchParams.get("ch");
  const selectedChapterNum =
    chRaw != null && chRaw !== "" ? parseInt(chRaw, 10) : null;

  const chapterNumbers = useMemo(() => extractChapterNumbers(outlineTree), [outlineTree]);

  const filledChapters = useMemo(
    () =>
      [...chapters]
        .filter((c) => c.status !== "生成中")
        .sort((a, b) => a.chapter_number - b.chapter_number),
    [chapters],
  );
  const filledChapterNums = useMemo(() => filledChapters.map((c) => c.chapter_number), [filledChapters]);
  const hasFilledChapters = filledChapterNums.length > 0;

  const effectiveChapterNum = useMemo(() => {
    if (chapterNumbers.length === 0) return null;
    if (selectedChapterNum == null || Number.isNaN(selectedChapterNum)) return null;
    if (hasFilledChapters) {
      return filledChapterNums.includes(selectedChapterNum) ? selectedChapterNum : null;
    }
    return chapterNumbers.includes(selectedChapterNum) ? selectedChapterNum : null;
  }, [chapterNumbers, selectedChapterNum, hasFilledChapters, filledChapterNums]);

  useEffect(() => {
    const fetchWork = async () => {
      try {
        const [workRes, chaptersRes, charsRes] = await Promise.all([
          authFetch(`${API_BASE}/works/${workId}`),
          authFetch(`${API_BASE}/works/${workId}/chapters`),
          authFetch(`${API_BASE}/works/${workId}/characters`),
        ]);
        if (!workRes.ok) throw new Error("加载失败");
        if (!chaptersRes.ok) throw new Error("加载章节失败");
        const data = await workRes.json();
        const chaptersData = await chaptersRes.json();
        const charsData = charsRes && charsRes.ok ? await charsRes.json() : [];
        setWork(data);
        setOutlineTree(data.outline_tree);
        setChapters(chaptersData);
        setCharacters(charsData);
      } catch (err) {
        setError(err.message || "加载失败");
      } finally {
        setLoading(false);
      }
    };
    fetchWork();
  }, [workId]);

  useEffect(
    () => () => {
      if (treePulseTimerRef.current) {
        window.clearTimeout(treePulseTimerRef.current);
        treePulseTimerRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    if (loading || mainTab !== "chapter" || chapterNumbers.length === 0) return;

    const fromUrl =
      selectedChapterNum != null && !Number.isNaN(selectedChapterNum) ? selectedChapterNum : null;

    if (hasFilledChapters) {
      if (fromUrl != null && filledChapterNums.includes(fromUrl)) return;
      const first = filledChapterNums[0];
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          n.set("tab", "chapter");
          n.set("ch", String(first));
          return n;
        },
        { replace: true },
      );
      return;
    }

    if (fromUrl != null && chapterNumbers.includes(fromUrl)) return;
    const first = chapterNumbers[0];
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("tab", "chapter");
        n.set("ch", String(first));
        return n;
      },
      { replace: true },
    );
  }, [
    loading,
    mainTab,
    chapterNumbers,
    hasFilledChapters,
    filledChapterNums,
    selectedChapterNum,
    setSearchParams,
  ]);

  useEffect(() => {
    if (mainTab !== "chapter" || effectiveChapterNum == null) return;
    const existing = chapters.find((c) => c.chapter_number === effectiveChapterNum);
    if (existing) {
      setSelectedChapter(existing);
      setTitleDraft(existing.title);
      setContentDraft(existing.content);
    } else {
      setSelectedChapter(null);
      setTitleDraft("");
      setContentDraft("");
    }
    setEvaluationResult(null);
    setEvaluationError("");
  }, [mainTab, effectiveChapterNum, chapters]);

  /** 正文高度随字数变化，避免固定 min-height 在文末留出大块空白 */
  useLayoutEffect(() => {
    if (mainTab !== "chapter") return;
    const el = chapterTextareaRef.current;
    if (!el || !contentDraft) return;
    el.style.height = "auto";
    el.style.height = `${Math.max(el.scrollHeight, 120)}px`;
  }, [mainTab, contentDraft, effectiveChapterNum]);

  useEffect(() => {
    if (!chatResizing) return undefined;
    const minWidth = 320;
    const maxWidth = 760;
    const onMouseMove = (e) => {
      const delta = resizeStartRef.current.x - e.clientX;
      const nextWidth = Math.min(maxWidth, Math.max(minWidth, resizeStartRef.current.width + delta));
      setChatPanelWidth(nextWidth);
    };
    const onMouseUp = () => setChatResizing(false);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [chatResizing]);

  const saveOutline = async (tree) => {
    setSaving(true);
    try {
      const res = await authFetch(`${API_BASE}/works/${workId}/outline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outline_tree: tree }),
      });
      if (res.ok) {
        const data = await res.json();
        setWork(data);
      }
    } catch {
      /* silently fail */
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateNode = (nodeId, fields) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      for (const list of [next.timeline, next.branches, next.foreshadowing]) {
        const node = list?.find((n) => n.id === nodeId);
        if (node) {
          Object.assign(node, fields);
          break;
        }
      }
      saveOutline(next);
      return next;
    });
  };

  const handleDeleteNode = (nodeId) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      next.timeline = (next.timeline || []).filter((n) => n.id !== nodeId);
      next.branches = (next.branches || []).filter((n) => n.id !== nodeId);
      next.foreshadowing = (next.foreshadowing || []).filter((n) => n.id !== nodeId);
      saveOutline(next);
      return next;
    });
  };

  const handleAddBranch = (attachTo, side) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      const host = (next.timeline || []).find((n) => n.id === attachTo);
      const cs = parsePositiveChapterInt(host?.chapter_start) ?? 1;
      const ceRaw = parsePositiveChapterInt(host?.chapter_end);
      const ce = ceRaw != null && ceRaw >= cs ? ceRaw : cs;
      next.branches = [
        ...(next.branches || []),
        {
          id: `B${Date.now()}`,
          attach_to: attachTo,
          side,
          name: "新支线",
          summary: "",
          chapter_start: cs,
          chapter_end: ce,
        },
      ];
      saveOutline(next);
      return next;
    });
  };

  const handleUpdateStory = (field, value) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      next.story = next.story || {};
      next.story[field] = value;
      saveOutline(next);
      return next;
    });
  };

  const handleTreeNodeSelect = (node) => {
    if (!node?.type || !node?.id) return;
    setGraphFocus(node);
  };

  const handleGraphNodeSelect = (node) => {
    if (!node?.type || !node?.id) return;
    setGraphFocus(node);
    setTreePulseFocus(node);
    if (treePulseTimerRef.current) window.clearTimeout(treePulseTimerRef.current);
    treePulseTimerRef.current = window.setTimeout(() => {
      setTreePulseFocus(null);
      treePulseTimerRef.current = null;
    }, 700);
  };

  const setTabOutline = () => {
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("tab", "outline");
        return n;
      },
      { replace: true },
    );
  };

  const selectChapter = (num) => {
    setSearchParams(
      (prev) => {
        const n = new URLSearchParams(prev);
        n.set("tab", "chapter");
        n.set("ch", String(num));
        return n;
      },
      { replace: true },
    );
  };

  const refreshChapters = async () => {
    try {
      const chaptersRes = await authFetch(`${API_BASE}/works/${workId}/chapters`);
      if (chaptersRes.ok) {
        const chaptersData = await chaptersRes.json();
        setChapters(chaptersData);
        // Update selected chapter content if viewing a chapter
        if (effectiveChapterNum) {
          const updated = chaptersData.find((c) => c.chapter_number === effectiveChapterNum);
          if (updated) {
            setSelectedChapter(updated);
            setTitleDraft(updated.title);
            setContentDraft(updated.content || "");
          }
        }
      }
    } catch { /* ignore */ }
  };

  const refreshCharacters = async () => {
    try {
      const res = await authFetch(`${API_BASE}/works/${workId}/characters`);
      if (res.ok) {
        const data = await res.json();
        setCharacters(data);
      }
    } catch { /* ignore */ }
  };

  const fetchChapterIntel = async (chapterNumber) => {
    if (!chapterNumber) return;
    try {
      const res = await authFetch(`${API_BASE}/works/${workId}/chapters/${chapterNumber}/intel`);
      if (!res.ok) return;
      const data = await res.json();
      handleChapterIntelUpdate(chapterNumber, data);
    } catch {
      // ignore
    }
  };

  const handleSaveChapter = async () => {
    if (!effectiveChapterNum || savingChapter) return;
    setSavingChapter(true);
    try {
      const res = await authFetch(`${API_BASE}/works/${workId}/chapters/${effectiveChapterNum}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: titleDraft, content: contentDraft }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "保存失败" }));
        throw new Error(err.detail || "保存失败");
      }
      const updated = await res.json();
      setChapters((prev) => {
        const idx = prev.findIndex((c) => c.chapter_number === updated.chapter_number);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = updated;
          return next;
        }
        return [...prev, updated];
      });
      setSelectedChapter(updated);
    } catch (err) {
      alert(`保存失败：${err.message}`);
    } finally {
      setSavingChapter(false);
    }
  };

  const handleEvaluateChapter = async () => {
    if (!effectiveChapterNum || evaluatingChapter) return;
    if (!contentDraft.trim()) {
      setEvaluationError("当前章节正文为空，无法评估。");
      setEvaluationResult(null);
      return;
    }
    setEvaluatingChapter(true);
    setEvaluationError("");
    try {
      const res = await authFetch(`${API_BASE}/evaluation/works/${workId}/chapters/${effectiveChapterNum}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chapter_content: contentDraft }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `评估失败（HTTP ${res.status}）`);
      }
      setEvaluationResult(data);
    } catch (err) {
      setEvaluationResult(null);
      setEvaluationError(err.message || "评估失败");
    } finally {
      setEvaluatingChapter(false);
    }
  };

  useEffect(() => {
    if (mainTab !== "chapter" || effectiveChapterNum == null) return;
    fetchChapterIntel(effectiveChapterNum);
  }, [mainTab, effectiveChapterNum, workId]);

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </main>
    );
  }

  if (error || !work) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="space-y-4 text-center">
          <p className="text-red-500">{error || "作品不存在"}</p>
          <Button asChild variant="outline">
            <Link to="/dashboard">返回首页</Link>
          </Button>
        </div>
      </main>
    );
  }

  const story = outlineTree?.story || {};
  const createdDate = work.created_at ? new Date(work.created_at).toLocaleDateString("zh-CN") : "";

  const wordCount = contentDraft ? contentDraft.replace(/\s/g, "").length : 0;
  const generatedCount = chapters.filter((c) => c.status !== "生成中").length;
  const currentChapterIntel = effectiveChapterNum ? chapterIntelByNumber[effectiveChapterNum] : null;

  const handleChapterIntelUpdate = (chapterNumber, patch) => {
    if (!chapterNumber) return;
    setChapterIntelByNumber((prev) => ({
      ...prev,
      [chapterNumber]: normalizeChapterIntel(prev[chapterNumber], patch),
    }));
  };

  return (
    <main className="flex h-screen flex-col bg-[linear-gradient(145deg,_#f8fafc_0%,_#ecfeff_45%,_#e2e8f0_100%)]">
      <section className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur sm:px-6">
        <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-4">
          <Button asChild variant="ghost" size="sm" className="shrink-0">
            <Link to="/dashboard">
              <ArrowLeft className="mr-1 h-4 w-4" /> 返回
            </Link>
          </Button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-slate-900">
              <EditableText
                value={story.title || work.title}
                onSave={(val) => handleUpdateStory("title", val)}
                className="text-lg font-semibold text-slate-900"
              />
            </h1>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <EditableText
                value={story.genre || work.genre}
                onSave={(val) => handleUpdateStory("genre", val)}
                className="text-xs text-slate-500"
              />
              {story.volume && <span>· {story.volume}</span>}
              {createdDate && (
                <span className="flex items-center gap-1">
                  <Calendar className="h-3 w-3" /> {createdDate}
                </span>
              )}
              {chapterNumbers.length > 0 && (
                <span className="text-slate-400">
                  · {generatedCount}/{chapterNumbers.length} 章已有正文
                </span>
              )}
              {saving && <span className="text-slate-400">大纲保存中...</span>}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
            <Button
              variant={mainTab === "outline" ? "secondary" : "ghost"}
              size="sm"
              className="h-8 gap-1 px-2 sm:px-3"
              onClick={setTabOutline}
            >
              <LayoutList className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">大纲</span>
            </Button>
          </div>

          <Button variant={chatOpen ? "default" : "outline"} size="sm" onClick={() => setChatOpen(!chatOpen)}>
            <Bot className="mr-1 h-4 w-4" />
            AI 助手
          </Button>
        </div>
      </section>

      <div className="flex flex-1 overflow-hidden">
        <aside
          className={`flex shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 ${
            sidebarCollapsed ? "w-12" : "w-[200px] sm:w-[220px]"
          }`}
        >
          <div className="flex items-center justify-end border-b border-slate-100 px-1 py-1">
            <Button variant="ghost" size="sm" className="h-8 w-8 shrink-0 p-0" onClick={() => setSidebarCollapsed((c) => !c)}>
              {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </Button>
          </div>

          {!sidebarCollapsed ? (
            <>
              <div className="px-3 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">章节</div>
              <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
                {chapterNumbers.length === 0 ? (
                  <p className="px-2 py-4 text-center text-xs text-slate-400">大纲中暂无章节区间</p>
                ) : filledChapters.length === 0 ? (
                  <p className="px-2 py-4 text-center text-xs text-slate-400">暂无草稿章节</p>
                ) : (
                  filledChapters.map((ch) => {
                    const num = ch.chapter_number;
                    const status = ch.status;
                    const isActive = mainTab === "chapter" && num === effectiveChapterNum;
                    return (
                      <button
                        key={num}
                        type="button"
                        onClick={() => selectChapter(num)}
                        className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm transition-colors ${
                          isActive ? "bg-blue-50 font-medium text-blue-700" : "text-slate-600 hover:bg-slate-100"
                        }`}
                      >
                        <BookOpen className={`h-3.5 w-3.5 shrink-0 ${isActive ? "text-blue-500" : "text-slate-400"}`} />
                        <span className="min-w-0 flex-1 truncate">{ch.title || `第${num}章`}</span>
                        <span
                          className={`shrink-0 rounded-full px-1 py-0.5 text-[9px] font-medium ${statusBadge(status)}`}
                          title={status}
                        >
                          {status.replace("已", "")}
                        </span>
                      </button>
                    );
                  })
                )}
              </nav>
              <div className="border-t border-slate-100 p-2">
                <Button asChild variant="ghost" size="sm" className="h-8 w-full justify-start gap-2 px-2 text-xs text-slate-600">
                  <Link to={`/works/${workId}/characters`}>
                    <Users className="h-3.5 w-3.5" /> 角色
                  </Link>
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-1 flex-col items-center gap-1 overflow-y-auto py-2">
                {filledChapters.map((ch) => {
                  const num = ch.chapter_number;
                  const isActive = mainTab === "chapter" && num === effectiveChapterNum;
                  return (
                    <button
                      key={num}
                      type="button"
                      title={ch.title || `第${num}章`}
                      onClick={() => selectChapter(num)}
                      className={`flex h-8 w-8 items-center justify-center rounded-md text-xs font-medium ${
                        isActive ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {num}
                    </button>
                  );
                })}
              </div>
              <div className="w-full border-t border-slate-100 p-2">
                <Button asChild variant="ghost" size="sm" className="h-8 w-full justify-center p-0 text-xs text-slate-600">
                  <Link to={`/works/${workId}/characters`} title="角色">
                    <Users className="h-4 w-4" />
                  </Link>
                </Button>
              </div>
            </>
          )}
        </aside>

        <div className="flex min-w-0 flex-1 overflow-hidden">
          <div className="pretty-scrollbar min-w-0 flex-1 overflow-auto px-4 pb-4 pt-4 sm:px-6 sm:pb-4 sm:pt-6">
            {mainTab === "outline" && (
              <div className="mx-auto grid max-w-[1600px] gap-5 xl:grid-cols-[380px_1fr]">
                <div className="min-w-0 rounded-[14px] border border-slate-300 bg-white p-4 shadow-[0_6px_24px_rgba(15,23,42,0.05)]">
                  <h3 className="mb-3 text-base font-semibold text-slate-800">剧情大纲树</h3>
                  <div className="pretty-scrollbar max-h-[780px] overflow-y-auto pr-1">
                    <InlineTree
                      tree={outlineTree}
                      pulseFocus={treePulseFocus}
                      onUpdateNode={handleUpdateNode}
                      onDeleteNode={handleDeleteNode}
                      onAddBranch={handleAddBranch}
                      onSelectNode={handleTreeNodeSelect}
                    />
                  </div>
                </div>
                <div className="min-w-0 space-y-4">
                  <RelationGraphPanel
                    tree={outlineTree}
                    characters={characters}
                    focus={graphFocus}
                    pulseFocus={null}
                    onNodeSelect={handleGraphNodeSelect}
                    onCharacterSelect={setSelectedCharacter}
                  />
                  <CharacterCardsPanel characters={characters} onCharacterSelect={setSelectedCharacter} />
                </div>
              </div>
            )}

            {mainTab === "chapter" && (
              <div className="mx-auto grid w-full max-w-[1400px] gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
                <div className="min-w-0">
                {chapterNumbers.length === 0 ? (
                  <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white/60 p-8 text-center text-slate-500">
                    <p className="text-sm">请先在「大纲」中为时间线配置章节区间</p>
                    <Button variant="outline" size="sm" className="mt-4" onClick={setTabOutline}>
                      去编辑大纲
                    </Button>
                  </div>
                ) : effectiveChapterNum == null ? (
                  <div className="flex flex-1 items-center justify-center text-slate-400">
                    <Loader2 className="h-6 w-6 animate-spin" />
                  </div>
                ) : (
                  <>
                    <div className="mb-4 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/90 p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
                        <Input
                          value={titleDraft}
                          onChange={(e) => setTitleDraft(e.target.value)}
                          placeholder={`第${effectiveChapterNum}章 标题`}
                          className="w-full text-sm font-medium sm:max-w-[320px]"
                        />
                        <span className="text-xs text-slate-400">{wordCount} 字</span>
                        {selectedChapter && (
                          <span className={`w-fit rounded-full px-2 py-0.5 text-[10px] font-medium ${statusBadge(selectedChapter.status)}`}>
                            {selectedChapter.status}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleSaveChapter}
                          disabled={savingChapter || (!titleDraft && !contentDraft)}
                        >
                          {savingChapter ? (
                            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Save className="mr-1 h-3.5 w-3.5" />
                          )}
                          保存
                        </Button>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-200 bg-white/90 p-4 shadow-sm">
                      {contentDraft ? (
                        <Textarea
                          ref={chapterTextareaRef}
                          value={contentDraft}
                          onChange={(e) => setContentDraft(e.target.value)}
                          className="min-h-[120px] resize-none overflow-hidden border-0 bg-transparent p-0 text-[15px] leading-[1.8] text-slate-800 shadow-none focus-visible:ring-0"
                          placeholder="开始写作..."
                        />
                      ) : (
                        <div className="flex flex-col items-center justify-center gap-4 py-10">
                          <div className="rounded-full bg-slate-100 p-4">
                            <PenLine className="h-8 w-8 text-slate-400" />
                          </div>
                          <p className="text-sm text-slate-500">第 {effectiveChapterNum} 章尚未生成正文</p>
                          <Button variant="outline" onClick={() => setChatOpen(true)}>
                            <Sparkles className="mr-1 h-4 w-4" />
                            在 AI 对话中生成
                          </Button>
                        </div>
                      )}
                    </div>

                    {(evaluationError || evaluationResult) && (
                      <div className="mt-4 rounded-xl border border-slate-200 bg-white/90 p-4 shadow-sm">
                        <div className="mb-3 flex items-center justify-between">
                          <h3 className="text-sm font-semibold text-slate-800">章节评估</h3>
                          {evaluationResult?.chapter_title && (
                            <span className="text-xs text-slate-500">{evaluationResult.chapter_title}</span>
                          )}
                        </div>

                        {evaluationError ? (
                          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{evaluationError}</p>
                        ) : (
                          <div className="grid gap-3 md:grid-cols-2">
                            {[
                              { key: "editor", label: "编辑视角" },
                              { key: "reader", label: "读者视角" },
                            ].map((item) => {
                              const r = evaluationResult?.[item.key];
                              if (!r) return null;
                              return (
                                <article key={item.key} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                                  <div className="mb-2 flex items-center justify-between">
                                    <span className="text-sm font-medium text-slate-800">{item.label}</span>
                                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700">
                                      {r.total_score}/60
                                    </span>
                                  </div>
                                  <p className="mb-1 text-xs font-medium text-slate-600">问题</p>
                                  <ul className="mb-2 list-disc space-y-0.5 pl-4 text-xs text-slate-600">
                                    {(r.issues || []).slice(0, 3).map((v, i) => <li key={`${item.key}-issue-${i}`}>{v}</li>)}
                                  </ul>
                                  <p className="mb-1 text-xs font-medium text-slate-600">建议</p>
                                  <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-600">
                                    {(r.suggestions || []).slice(0, 3).map((v, i) => <li key={`${item.key}-sugg-${i}`}>{v}</li>)}
                                  </ul>
                                </article>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
                </div>
                {effectiveChapterNum != null && chapterNumbers.length > 0 && (
                  <div className="min-w-0 xl:sticky xl:top-0 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto xl:pretty-scrollbar">
                    <ChapterIntelSidebar
                      chapterNumber={effectiveChapterNum}
                      intel={currentChapterIntel}
                      outlineTree={outlineTree}
                      characters={characters}
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          {chatOpen && (
            <div
              className={`relative hidden shrink-0 overflow-hidden rounded-l-2xl border-l border-slate-200 bg-white md:flex md:flex-col ${
                chatResizing ? "select-none" : ""
              }`}
              style={{ width: `${chatPanelWidth}px` }}
            >
              <div
                className="absolute left-0 top-0 z-10 hidden h-full w-2 -translate-x-1/2 cursor-col-resize bg-transparent hover:bg-blue-200/40 md:block"
                onMouseDown={(e) => {
                  resizeStartRef.current = { x: e.clientX, width: chatPanelWidth };
                  setChatResizing(true);
                }}
                title="拖拽调整宽度"
              />
              <SupervisorChatPanel
                workId={workId}
                onOutlineUpdated={(newTree) => setOutlineTree(newTree)}
                onChapterUpdated={() => refreshChapters()}
                onCharactersUpdated={() => refreshCharacters()}
                onChapterIntelUpdate={handleChapterIntelUpdate}
              />
            </div>
          )}
        </div>
      </div>

      {chatOpen && (
        <div className="flex max-h-[40vh] shrink-0 flex-col border-t border-slate-200 bg-white md:hidden">
          <div className="border-b border-slate-100 px-3 py-2 text-center text-xs text-slate-500">AI 对话（小屏）</div>
          <div className="min-h-[200px] flex-1 overflow-hidden">
            <SupervisorChatPanel
              workId={workId}
              onOutlineUpdated={(newTree) => setOutlineTree(newTree)}
              onChapterUpdated={() => refreshChapters()}
              onCharactersUpdated={() => refreshCharacters()}
              onChapterIntelUpdate={handleChapterIntelUpdate}
            />
          </div>
        </div>
      )}

      <CharacterDetailDrawer
        character={selectedCharacter}
        outlineTree={outlineTree}
        onClose={() => setSelectedCharacter(null)}
        onLinkClick={(link) => {
          if (link?.timeline_id) {
            setGraphFocus({ type: "timeline", id: link.timeline_id });
          }
        }}
      />
    </main>
  );
}
