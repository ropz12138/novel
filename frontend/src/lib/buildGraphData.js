import { sortTimelineNodes } from "./outlineTimelineSort.js";

function formatEdgeLabel(text, maxPerLine = 8, maxLines = 2) {
  const raw = String(text || "").replace(/\s+/g, " ").trim();
  if (!raw) return "";
  const chunks = [];
  for (let i = 0; i < raw.length; i += maxPerLine) chunks.push(raw.slice(i, i + maxPerLine));
  if (chunks.length <= maxLines) return chunks.join("\n");
  const kept = chunks.slice(0, maxLines);
  const last = kept[maxLines - 1];
  kept[maxLines - 1] = `${last.slice(0, Math.max(0, maxPerLine - 1))}…`;
  return kept.join("\n");
}

export function buildGraphData(tree, characters) {
  // 新数据结构：outline.macro_phases / meso.meso_stages / foreshadowing / character_links
  const macroPhases = Array.isArray(tree?.outline?.macro_phases) ? tree.outline.macro_phases : [];
  const mesoStages = Array.isArray(tree?.meso?.meso_stages) ? tree.meso.meso_stages : [];
  const foreshadowing = Array.isArray(tree?.foreshadowing) ? tree.foreshadowing : [];
  const characterLinks = Array.isArray(tree?.character_links) ? tree.character_links : [];
  const chars = Array.isArray(characters) ? characters : [];

  // 兼容旧数据结构
  const legacyTimeline = Array.isArray(tree?.timeline) ? sortTimelineNodes(tree.timeline) : [];
  const legacyBranches = Array.isArray(tree?.branches) ? tree.branches : [];

  const useNewStructure = macroPhases.length > 0 || mesoStages.length > 0;
  const timeline = useNewStructure ? macroPhases : legacyTimeline;
  const branches = useNewStructure ? mesoStages : legacyBranches;

  const nodes = [];
  const edges = [];
  const edgeSeen = new Set();

  const addEdge = (id, from, to, attrs = {}) => {
    if (!from || !to) return;
    if (edgeSeen.has(id)) return;
    edgeSeen.add(id);
    edges.push({ id, from, to, ...attrs });
  };

  // 宏观阶段（蓝色椭圆）
  const timelineIdMap = new Map();
  timeline.forEach((t, idx) => {
    const rawId = String(t.id || `P${idx + 1}`);
    const nodeId = `t:${idx + 1}:${rawId}`;
    if (!timelineIdMap.has(rawId)) timelineIdMap.set(rawId, nodeId);
    nodes.push({
      id: nodeId,
      label: `${rawId}\n${useNewStructure ? (t.name || "宏观阶段") : (t.development_node || "主线节点")}`,
      group: "mainStory",
      shape: "ellipse",
    });
    if (idx > 0) {
      const prev = timeline[idx - 1];
      addEdge(
        `seq:${idx}`,
        `t:${idx}:${String(prev.id || `P${idx}`)}`,
        nodeId,
        { color: { color: "#2563eb" }, arrows: "to", width: 2 },
      );
    }
  });

  // 中纲阶段（绿色方框，挂载到宏观阶段）
  const branchIdMap = new Map();
  branches.forEach((b, idx) => {
    const rawId = String(b.id || `M${idx + 1}`);
    const nodeId = `b:${idx + 1}:${rawId}`;
    if (!branchIdMap.has(rawId)) branchIdMap.set(rawId, nodeId);
    nodes.push({
      id: nodeId,
      label: `${rawId}\n${useNewStructure ? (b.name || "中纲阶段") : (b.name || "支线")}`,
      group: "branchStory",
      shape: "box",
    });
    // 挂载到宏观阶段（macro_phase_id）或主线节点（attach_to）
    const attachKey = useNewStructure ? b.macro_phase_id : b.attach_to;
    const attachTarget = timelineIdMap.get(String(attachKey || "")) || null;
    addEdge(
      `attach:${idx}`,
      attachTarget,
      nodeId,
      { color: { color: "#059669" }, arrows: "to", width: 1.5 },
    );
  });

  // Combined lookup: timeline first, then branch
  const allNodeIdMap = new Map([...timelineIdMap, ...branchIdMap]);

  // 伏笔（橙色圆）
  foreshadowing.forEach((f, idx) => {
    const rawId = String(f.id || `F${idx + 1}`);
    const nodeId = `f:${idx + 1}:${rawId}`;
    nodes.push({
      id: nodeId,
      label: rawId,
      group: "foreshadow",
      shape: "circle",
      size: 18,
    });
    const plantTarget = allNodeIdMap.get(String(f.plant_node || "")) || null;
    const payoffTarget = allNodeIdMap.get(String(f.payoff_node || "")) || null;
    addEdge(
      `plant:${idx}`,
      plantTarget,
      nodeId,
      { color: { color: "#d97706" }, arrows: "to", dashes: true, width: 1.5 },
    );
    addEdge(
      `payoff:${idx}`,
      nodeId,
      payoffTarget,
      { color: { color: "#d97706" }, arrows: "to", dashes: [5, 5], width: 1.5 },
    );
  });

  // 角色节点（方框）
  chars.forEach((c, idx) => {
    const cid = `c:${idx + 1}:${c.id || c.name || "unknown"}`;
    nodes.push({
      id: cid,
      label: `${c.name || "未知角色"}\n(${c.role_type || "配角"})`,
      group: "character",
      shape: "box",
    });

  });

  const byName = new Map(chars.map((c, i) => [c.name, `c:${i + 1}:${c.id || c.name || "unknown"}`]));

  // 角色-剧情关联线
  if (characterLinks.length > 0) {
    characterLinks.forEach((link, i) => {
      if (!link || typeof link !== "object") return;
      const sourceId = byName.get(link.character_name);
      const timelineTarget = timelineIdMap.get(String(link.timeline_id || ""));
      if (!sourceId || !timelineTarget) return;
      const type = String(link.link_type || "appear");
      const colorMap = {
        appear: "#2563eb",
        lead: "#2563eb",
        conflict: "#ef4444",
        ally: "#059669",
        foreshadow_trigger: "#d97706",
        foreshadow_payoff: "#d97706",
      };
      const edgeColor = colorMap[type] || "#2563eb";
      const dashed = type === "conflict" || type.startsWith("foreshadow_");
      addEdge(
        `clink:${i}`,
        sourceId,
        timelineTarget,
        {
          label: formatEdgeLabel(link.summary),
          color: { color: edgeColor },
          arrows: "to",
          dashes: dashed ? [5, 5] : false,
          width: Number(link.weight) > 0 ? Math.min(4, Math.max(1, Number(link.weight))) : 2,
        },
      );
    });
  } else {
    // 没有显式关联时，按 first_appearance_stage 直接匹配 meso_stage id
    chars.forEach((c, idx) => {
      const cid = `c:${idx + 1}:${c.id || c.name || "unknown"}`;
      const stage = String(c.first_appearance_stage ?? "").trim();
      if (stage) {
        const hit = timeline.find((t) => String(t.id || "") === stage || String(t.meso_stage_id || "") === stage);
        if (hit) {
          addEdge(
            `appear:${idx}`,
            cid,
            timelineIdMap.get(String(hit.id || "")) || null,
            { color: { color: "#2563eb" }, arrows: "to", width: 1.5 },
          );
        }
      }
    });
  }

  // 角色关系线
  chars.forEach((c, idx) => {
    const sourceId = `c:${idx + 1}:${c.id || c.name || "unknown"}`;
    const rel = c.relationships && typeof c.relationships === "object" ? c.relationships : {};
    Object.entries(rel).forEach(([targetName, desc]) => {
      const targetId = byName.get(targetName);
      if (!targetId || targetId === sourceId) return;
      const dashed = String(desc || "").includes("敌") || String(desc || "").includes("猜忌");
      addEdge(
        `rel:${idx}:${targetName}`,
        sourceId,
        targetId,
        {
          label: formatEdgeLabel(desc),
          color: { color: "#ef4444" },
          dashes: dashed ? [5, 5] : false,
          width: 2,
        },
      );
    });
  });

  return { nodes, edges };
}
