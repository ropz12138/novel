function cleanLine(line) {
  return line.replace(/^\s*[-*•]\s*/, "").replace(/^\s*\d+[.)、]\s*/, "").trim();
}

function shortText(text, max = 20) {
  const t = text.replace(/[：:]/g, " ").trim();
  return t.length > max ? `${t.slice(0, max)}...` : t;
}

function splitSections(outlineText) {
  const lines = outlineText.split("\n");
  const main = [];
  const side = [];
  let mode = "";

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.includes("主线")) {
      mode = "main";
      continue;
    }
    if (line.includes("支线")) {
      mode = "side";
      continue;
    }
    if (line.startsWith("【") && line.endsWith("】")) {
      mode = "";
      continue;
    }

    const cleaned = cleanLine(line);
    if (!cleaned) continue;

    if (mode === "main") main.push(cleaned);
    if (mode === "side") side.push(cleaned);
  }

  return { main, side };
}

function buildChapterRange(index) {
  const start = index * 12 + 1;
  const end = start + 11;
  return `第${start}-${end}章`;
}

function buildTimeLabel(index) {
  const labels = ["开端期", "发展期", "对抗期", "高潮期", "收束期"];
  return labels[index] || `阶段${index + 1}`;
}

export function buildTreeFromOutline(outlineText) {
  const { main, side } = splitSections(outlineText || "");
  const mainRaw = main.length ? main : ["主角卷入核心冲突", "阵营对抗持续升级", "阶段高潮与反转"];
  const sideRaw = side.length ? side : ["同伴成长线", "势力博弈线", "伏笔回收线"];

  const timeline = mainRaw.map((text, idx) => ({
    id: `N${idx + 1}`,
    devNode: shortText(text),
    timeNode: buildTimeLabel(idx),
    chapterRange: buildChapterRange(idx),
    sideNodes: []
  }));

  sideRaw.forEach((text, idx) => {
    const attachIndex = idx % timeline.length;
    timeline[attachIndex].sideNodes.push({
      id: `S${idx + 1}`,
      text: shortText(text),
      direction: idx % 2 === 0 ? "left" : "right"
    });
  });

  return { timeline };
}
