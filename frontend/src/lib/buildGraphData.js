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
  const timeline = Array.isArray(tree?.timeline) ? sortTimelineNodes(tree.timeline) : [];
  const branches = Array.isArray(tree?.branches) ? tree.branches : [];
  const foreshadowing = Array.isArray(tree?.foreshadowing) ? tree.foreshadowing : [];
  const characterLinks = Array.isArray(tree?.character_links) ? tree.character_links : [];
  const chars = Array.isArray(characters) ? characters : [];

  const nodes = [];
  const edges = [];
  const edgeSeen = new Set();

  const addEdge = (id, from, to, attrs = {}) => {
    if (!from || !to) return;
    if (edgeSeen.has(id)) return;
    edgeSeen.add(id);
    edges.push({ id, from, to, ...attrs });
  };

  const timelineIdMap = new Map();
  timeline.forEach((t, idx) => {
    const rawId = String(t.id || `T${idx + 1}`);
    const nodeId = `t:${idx + 1}:${rawId}`;
    if (!timelineIdMap.has(rawId)) timelineIdMap.set(rawId, nodeId);
    nodes.push({
      id: nodeId,
      label: `${rawId}\n${t.development_node || "主线节点"}`,
      group: "mainStory",
      shape: "ellipse",
    });
    if (idx > 0) {
      const prev = timeline[idx - 1];
      addEdge(
        `seq:${idx}`,
        `t:${idx}:${String(prev.id || `T${idx}`)}`,
        nodeId,
        { color: { color: "#2563eb" }, arrows: "to", width: 2 },
      );
    }
  });

  const branchIdMap = new Map();
  branches.forEach((b, idx) => {
    const rawId = String(b.id || `B${idx + 1}`);
    const nodeId = `b:${idx + 1}:${rawId}`;
    if (!branchIdMap.has(rawId)) branchIdMap.set(rawId, nodeId);
    nodes.push({
      id: nodeId,
      label: `${rawId}\n${b.name || "支线"}`,
      group: "branchStory",
      shape: "box",
    });
    const attachTarget = timelineIdMap.get(String(b.attach_to || "")) || null;
    addEdge(
      `attach:${idx}`,
      attachTarget,
      nodeId,
      { color: { color: "#059669" }, arrows: "to", width: 1.5 },
    );
  });

  // Combined lookup: timeline first, then branch
  const allNodeIdMap = new Map([...timelineIdMap, ...branchIdMap]);

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
    chars.forEach((c, idx) => {
      const cid = `c:${idx + 1}:${c.id || c.name || "unknown"}`;
      const first = Number.parseInt(String(c.first_chapter ?? ""), 10);
      if (Number.isFinite(first)) {
        const hit = timeline.find(
          (t) =>
            Number.isFinite(Number(t.chapter_start)) &&
            Number.isFinite(Number(t.chapter_end)) &&
            first >= Number(t.chapter_start) &&
            first <= Number(t.chapter_end),
        );
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
