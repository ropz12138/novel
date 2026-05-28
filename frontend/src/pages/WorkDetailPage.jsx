import { API_BASE } from "../lib/runtime-config";
import { authFetch } from "../lib/authFetch";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
  StopCircle,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { extractChapterNumbers } from "../lib/chapterOutline";
import { parsePositiveChapterInt } from "../lib/outlineChapterInput";
import { relationGraphStabilizationFallbackMs } from "../lib/relationGraphLoading";
import { sortTimelineNodes } from "../lib/outlineTimelineSort";
import { buildGraphData } from "../lib/buildGraphData";
import { sessionApi } from "../lib/api";
import { CharacterDetailDrawer } from "../components/CharacterDetailDrawer";
import { RelationGraphLoadingOverlay } from "../components/RelationGraphLoadingOverlay";
import { useSupervisorChat } from "../hooks/useSupervisorChat";
import { ChatTimeline } from "../components/supervisor/ChatTimeline";
import { useSmartScroll } from "../hooks/useSmartScroll";


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
  const [expandedNodes, setExpandedNodes] = useState(new Set());

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

  const toggleExpand = useCallback((type, id) => {
    const key = `${type}:${String(id)}`;
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const isExpanded = useCallback((type, id) => {
    return expandedNodes.has(`${type}:${String(id)}`);
  }, [expandedNodes]);

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
                onClick={() => {
                  toggleExpand("timeline", node.id);
                  onSelectNode?.({ type: "timeline", id: node.id });
                }}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <h4 className={`${isExpanded("timeline", node.id) ? "" : "truncate"} text-sm font-semibold text-slate-800`}>
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
                <p className={`${isExpanded("timeline", node.id) ? "" : "line-clamp-2"} text-xs text-slate-600`}>{node.summary || "（暂无摘要）"}</p>
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
                        onClick={() => {
                          toggleExpand("branch", b.id);
                          onSelectNode?.({ type: "branch", id: b.id });
                        }}
                      >
                        <div className="absolute -left-[13px] top-3 w-2 border-t border-slate-200" />
                        <div className="flex items-center justify-between gap-2">
                          <div className={`${isExpanded("branch", b.id) ? "" : "truncate"} text-xs font-semibold text-slate-800`}>
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
                        <p className={`${isExpanded("branch", b.id) ? "" : "line-clamp-1"} text-[11px] text-slate-600`}>{b.summary || "（暂无支线摘要）"}</p>
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
                                  toggleExpand("foreshadowing", f.id);
                                  onSelectNode?.({ type: "foreshadowing", id: f.id });
                                }}
                              >
                                <div className="absolute -left-[9px] top-2.5 w-1.5 border-t border-slate-200" />
                                <div className="flex items-center justify-between gap-1">
                                  <div className={`${isExpanded("foreshadowing", f.id) ? "" : "truncate"} text-[11px] font-semibold text-slate-800`}>
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
                                <p className={`${isExpanded("foreshadowing", f.id) ? "" : "line-clamp-1"} text-[10px] text-slate-600`}>{f.content || "（暂无伏笔内容）"}</p>
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
                      onClick={() => {
                        toggleExpand("foreshadowing", f.id);
                        onSelectNode?.({ type: "foreshadowing", id: f.id });
                      }}
                    >
                      <div className="absolute -left-[13px] top-3 w-2 border-t border-slate-200" />
                      <div className="flex items-center justify-between gap-2">
                        <div className={`${isExpanded("foreshadowing", f.id) ? "" : "truncate"} text-xs font-semibold text-slate-800`}>
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
                      <p className={`${isExpanded("foreshadowing", f.id) ? "" : "line-clamp-1"} text-[11px] text-slate-600`}>{f.content || "（暂无伏笔内容）"}</p>
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
                onClick={() => {
                  toggleExpand("foreshadowing", f.id);
                  onSelectNode?.({ type: "foreshadowing", id: f.id });
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className={`${isExpanded("foreshadowing", f.id) ? "" : "truncate"} text-xs font-semibold text-slate-800`}>
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
                <p className={`${isExpanded("foreshadowing", f.id) ? "" : "line-clamp-1"} text-[11px] text-slate-600`}>{f.content || "（暂无伏笔内容）"}</p>
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

function SupervisorChatPanel({ workId, onOutlineUpdated, onChapterUpdated, onCharactersUpdated, onChapterIntelUpdate }) {
  const chat = useSupervisorChat({
    workId,
    autoMode: true,
    callbacks: {
      onOutlineUpdated,
      onChapterUpdated,
      onCharactersUpdated,
      onChapterIntelUpdate: (data) => {
        if (onChapterIntelUpdate) {
          onChapterIntelUpdate(data.chapter_number, data);
        }
      },
    },
  });

  // Local session dropdown state (not in hook)
  const [sessions, setSessions] = useState([]);
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const dropdownRef = useRef(null);

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

  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setSessionListOpen(false);
      }
    };
    if (sessionListOpen) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [sessionListOpen]);

  const scrollContainerRef = useRef(null);
  const { stickToBottom, scrollToBottom } = useSmartScroll(scrollContainerRef, [
    chat.timeline, chat.assistantDraft, chat.editDiff, chat.outlineDiff, chat.characterDiff, chat.running,
  ]);

  const handleNewSession = () => {
    if (chat.running) return;
    chat.resetState();
    setSessionListOpen(false);
  };

  const handleDeleteSession = async (id) => {
    if (chat.running) return;
    if (!confirm("确定删除这个对话？")) return;
    try {
      await sessionApi.deleteSupervisor(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (chat.sessionId === id) {
        handleNewSession();
      }
    } catch {
      // ignore
    }
  };

  const onSelectSession = async (session) => {
    setSessionListOpen(false);
    await chat.handleSelectSession(session);
  };

  const currentSessionTitle = useMemo(() => {
    if (!chat.sessionId) return "新对话";
    const s = sessions.find((s) => s.id === chat.sessionId);
    return s?.title || "新对话";
  }, [chat.sessionId, sessions]);

  // Override session_created to also refresh session list
  useEffect(() => {
    if (chat.sessionId) loadSessions();
  }, [chat.sessionId]);

  const confirmEdit = async (action, targetDiff) => {
    await chat.handleConfirmEdit(action, targetDiff);
  };

  return (
    <div className="flex h-full flex-col">
      {/* Session selector dropdown */}
      <div ref={dropdownRef} className="relative flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div className="flex min-w-0 max-w-[220px] flex-1 items-center gap-1">
          <button
            type="button"
            onClick={() => !chat.running && setSessionListOpen(!sessionListOpen)}
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-50"
            disabled={chat.running}
          >
            <span className="truncate">{currentSessionTitle}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          </button>
        </div>
        <button
          type="button"
          onClick={handleNewSession}
          disabled={chat.running}
          className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-500 disabled:opacity-50"
          title="新建对话"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
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
                  onClick={() => onSelectSession(s)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") onSelectSession(s);
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
                    s.id === chat.sessionId
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
                    disabled={chat.running}
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

      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-4 py-3 relative">
        <div className="space-y-3">
          <ChatTimeline
            timeline={chat.timeline}
            assistantDraft={chat.assistantDraft}
            editDiff={chat.editDiff}
            outlineDiff={chat.outlineDiff}
            characterDiff={chat.characterDiff}
            confirming={chat.confirming}
            running={chat.running}
            onToggleStep={chat.toggleStepPanel}
            onConfirmEdit={confirmEdit}
            onConfirmOutline={chat.handleConfirmOutline}
          />
          {chat.running && !chat.timeline.some((item) => item.kind === "step" && item.status === "running") && !chat.editDiff && !chat.outlineDiff && !chat.characterDiff && (
            <div className="flex gap-2 justify-start">
              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500 animate-pulse">
                <Bot className="h-3 w-3" />
              </div>
              <div className="rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-500">思考中...</div>
            </div>
          )}
        </div>
        {!stickToBottom && (
          <button
            onClick={scrollToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded-full bg-white/90 border border-slate-200 px-3 py-1 text-xs text-slate-600 shadow-sm backdrop-blur hover:bg-white hover:border-blue-300 transition-colors"
          >
            <ChevronDown className="h-3 w-3" />
            回到底部
          </button>
        )}
      </div>
      <div className="shrink-0 px-4 py-3">
        <div className="flex items-end gap-2 pr-2">
          <Textarea
            value={chat.input}
            onChange={(e) => chat.setInput(e.target.value)}
            placeholder="输入指令... (如「修改大纲」「写第1章」「修改第1章的...」)"
            className="min-h-[40px] max-h-[120px] resize-none text-sm"
            rows={1}
            disabled={chat.running}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                chat.handleSend();
              }
            }}
          />
          <Button
            size="icon"
            className={`h-10 w-10 shrink-0 rounded-full ${chat.running ? "bg-red-500 hover:bg-red-600" : ""}`}
            onClick={chat.running ? chat.handleInterrupt : chat.handleSend}
            disabled={!chat.running && (!chat.input.trim())}
            aria-label={chat.running ? "中断任务" : "发送消息"}
          >
            {chat.running ? <StopCircle className="h-4 w-4" /> : <Send className="h-4 w-4" />}
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
  const outlineLinks = Array.isArray(intel?.outline_links) ? intel.outline_links : [];
  const [activeOutlineLink, setActiveOutlineLink] = useState(null);
  const timeline = Array.isArray(outlineTree?.timeline) ? outlineTree.timeline : [];
  const branches = Array.isArray(outlineTree?.branches) ? outlineTree.branches : [];
  const foreshadowing = Array.isArray(outlineTree?.foreshadowing) ? outlineTree.foreshadowing : [];

  useEffect(() => {
    setActiveOutlineLink(outlineLinks[0] || null);
  }, [chapterNumber, intel?.updated_at]);

  const inferOutlineLinkType = (link) => {
    const explicitType = String(link?.type || "").toLowerCase();
    if (explicitType === "branch") return "branch";
    if (explicitType === "foreshadowing" || explicitType === "foreshadow") return "foreshadowing";
    if (explicitType === "timeline" || explicitType === "main") return "timeline";
    const id = String(link?.id || "").toUpperCase();
    if (id.startsWith("B")) return "branch";
    if (id.startsWith("F")) return "foreshadowing";
    if (id.startsWith("T")) return "timeline";
    return "timeline";
  };

  const activeNode = useMemo(() => {
    if (!activeOutlineLink?.id) return null;
    const id = String(activeOutlineLink.id);
    const linkType = inferOutlineLinkType(activeOutlineLink);
    if (linkType === "branch") {
      return branches.find((n) => String(n.id) === id) || null;
    }
    if (linkType === "foreshadowing") {
      return foreshadowing.find((n) => String(n.id) === id) || null;
    }
    return timeline.find((n) => String(n.id) === id) || null;
  }, [activeOutlineLink, timeline, branches, foreshadowing]);

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
          {outlineLinks.slice(0, 6).map((n, idx) => (
            <button
              key={`tm-${idx}`}
              type="button"
              onClick={() => setActiveOutlineLink(n)}
              className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold transition ${
                activeOutlineLink?.id === n.id && inferOutlineLinkType(activeOutlineLink) === inferOutlineLinkType(n)
                  ? "border-blue-400 bg-blue-100 text-blue-800"
                  : "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"
              }`}
              title="点击查看节点详情"
            >
              {(inferOutlineLinkType(n) === "branch"
                ? "支线"
                : inferOutlineLinkType(n) === "foreshadowing"
                  ? "伏笔"
                  : "主线")}·{n.id || "节点"}
            </button>
          ))}
          {(intel?.involved_characters || []).slice(0, 6).map((c, idx) => (
            <span key={`ch-${idx}`} className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
              角色·{c.name || "未知"}
            </span>
          ))}
          {outlineLinks.length === 0 && (intel?.involved_characters || []).length === 0 && (
            <span className="text-xs text-slate-500">暂无可识别关联</span>
          )}
        </div>
        {activeOutlineLink && (
          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs text-slate-700">
            <p className="font-semibold text-slate-800">
              {(inferOutlineLinkType(activeOutlineLink) === "branch"
                ? "支线"
                : inferOutlineLinkType(activeOutlineLink) === "foreshadowing"
                  ? "伏笔"
                  : "主线")}节点 · {activeOutlineLink.id || "未知"}
            </p>
            <p className="mt-1 text-slate-600">
              名称：{activeNode?.name || activeNode?.development_node || activeNode?.content || "未命名节点"}
            </p>
            {(activeNode?.chapter_start || activeNode?.chapter_end) && (
              <p className="mt-1 text-slate-600">
                章节区间：第{activeNode?.chapter_start || "?"}-{activeNode?.chapter_end || "?"}章
              </p>
            )}
            {activeNode?.summary && <p className="mt-1 whitespace-pre-wrap text-slate-600">摘要：{activeNode.summary}</p>}
            {activeOutlineLink?.reason && (
              <p className="mt-1 whitespace-pre-wrap text-slate-600">关联原因：{activeOutlineLink.reason}</p>
            )}
          </div>
        )}
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
  const [deletingLastChapter, setDeletingLastChapter] = useState(false);
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
  const maxExistingChapterNum = useMemo(
    () => (chapters.length > 0 ? Math.max(...chapters.map((c) => c.chapter_number)) : null),
    [chapters],
  );

  const effectiveChapterNum = useMemo(() => {
    if (chapterNumbers.length === 0) return null;
    if (selectedChapterNum == null || Number.isNaN(selectedChapterNum)) return null;
    if (hasFilledChapters) {
      return filledChapterNums.includes(selectedChapterNum) ? selectedChapterNum : null;
    }
    return chapterNumbers.includes(selectedChapterNum) ? selectedChapterNum : null;
  }, [chapterNumbers, selectedChapterNum, hasFilledChapters, filledChapterNums]);
  const canDeleteCurrentChapter =
    effectiveChapterNum != null && maxExistingChapterNum != null && effectiveChapterNum === maxExistingChapterNum;

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
    const nextH = `${Math.max(el.scrollHeight, 120)}px`;
    if (el.style.height === nextH) return;
    const container = el.closest(".pretty-scrollbar") || el.parentElement;
    const prevScroll = container ? container.scrollTop : 0;
    el.style.height = nextH;
    if (container) container.scrollTop = prevScroll;
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

  const handleDeleteLastChapter = async () => {
    if (!canDeleteCurrentChapter || deletingLastChapter) return;
    if (!window.confirm(`确认删除第 ${effectiveChapterNum} 章吗？此操作不可撤销。`)) return;
    setDeletingLastChapter(true);
    try {
      const res = await authFetch(`${API_BASE}/works/${workId}/chapters/last`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "删除失败" }));
        throw new Error(err.detail || "删除失败");
      }

      const prevChapterNum =
        effectiveChapterNum != null
          ? chapters
              .map((c) => c.chapter_number)
              .filter((n) => n < effectiveChapterNum)
              .sort((a, b) => b - a)[0] ?? null
          : null;

      await refreshChapters();
      if (prevChapterNum != null) {
        selectChapter(prevChapterNum);
      } else {
        setSearchParams(
          (prev) => {
            const n = new URLSearchParams(prev);
            n.set("tab", "chapter");
            n.delete("ch");
            return n;
          },
          { replace: true },
        );
      }
    } catch (err) {
      alert(`删除失败：${err.message}`);
    } finally {
      setDeletingLastChapter(false);
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
  const isChapterDraftDirty = !!(
    selectedChapter &&
    (titleDraft !== (selectedChapter.title || "") || contentDraft !== (selectedChapter.content || ""))
  );

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
                          <span className={`w-fit rounded-full px-2 py-0.5 text-[10px] font-medium ${statusBadge(isChapterDraftDirty ? "草稿" : selectedChapter.status)}`}>
                            {isChapterDraftDirty ? "草稿" : selectedChapter.status}
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleSaveChapter}
                          disabled={savingChapter || deletingLastChapter || (!titleDraft && !contentDraft)}
                        >
                          {savingChapter ? (
                            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Save className="mr-1 h-3.5 w-3.5" />
                          )}
                          保存
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleDeleteLastChapter}
                          disabled={!canDeleteCurrentChapter || deletingLastChapter || savingChapter}
                          title={canDeleteCurrentChapter ? "删除当前末章" : "仅可删除当前末章"}
                          className="border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700"
                        >
                          {deletingLastChapter ? (
                            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="mr-1 h-3.5 w-3.5" />
                          )}
                          删除末章
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
