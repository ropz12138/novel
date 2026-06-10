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
    if (line.includes("主线") || line.includes("宏观")) {
      mode = "main";
      continue;
    }
    if (line.includes("支线") || line.includes("中纲")) {
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
  return [start, end];
}

function buildTimeLabel(index) {
  const labels = ["开端期", "发展期", "对抗期", "高潮期", "收束期"];
  return labels[index] || `阶段${index + 1}`;
}

export function buildTreeFromOutline(outlineText) {
  const { main, side } = splitSections(outlineText || "");
  const mainRaw = main.length ? main : ["主角卷入核心冲突", "阵营对抗持续升级", "阶段高潮与反转"];
  const sideRaw = side.length ? side : ["同伴成长线", "势力博弈线", "伏笔回收线"];

  const macroPhases = mainRaw.map((text, idx) => ({
    id: `P${idx + 1}`,
    name: shortText(text),
    goal: text,
    core_setting: "",
    chapter_range: buildChapterRange(idx),
  }));

  const mesoStages = sideRaw.map((text, idx) => {
    const attachIndex = idx % macroPhases.length;
    return {
      id: `M${idx + 1}`,
      name: shortText(text),
      type: "支线",
      cause: text,
      conflict: "",
      key_characters: [],
      twist: "",
      climax: "",
      outcome: "",
      macro_phase_id: macroPhases[attachIndex].id,
      chapter_range: buildChapterRange(attachIndex),
    };
  });

  return {
    outline: { macro_phases: macroPhases, core_characters: [], ending: {} },
    meso: { meso_stages: mesoStages },
    foreshadowing: [],
  };
}
