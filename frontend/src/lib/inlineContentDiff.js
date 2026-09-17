const TYPE_ORDER = { delete: 0, replace: 1, insert_after: 2 };

export function splitParagraphs(content) {
  const text = (content || "").trim();
  if (!text) return [];
  return text.split("\n\n");
}

export function joinParagraphs(paragraphs) {
  return paragraphs.join("\n\n");
}

export function buildContentDiffFromContents(originalContent, currentContent) {
  const oldParagraphs = splitParagraphs(originalContent);
  const newParagraphs = splitParagraphs(currentContent);
  const rows = oldParagraphs.length + 1;
  const cols = newParagraphs.length + 1;
  const lcs = Array.from({ length: rows }, () => Array(cols).fill(0));

  for (let i = oldParagraphs.length - 1; i >= 0; i -= 1) {
    for (let j = newParagraphs.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = oldParagraphs[i] === newParagraphs[j]
        ? lcs[i + 1][j + 1] + 1
        : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const matches = [];
  let oldIndex = 0;
  let newIndex = 0;
  while (oldIndex < oldParagraphs.length && newIndex < newParagraphs.length) {
    if (oldParagraphs[oldIndex] === newParagraphs[newIndex]) {
      matches.push([oldIndex, newIndex]);
      oldIndex += 1;
      newIndex += 1;
    } else if (lcs[oldIndex + 1][newIndex] >= lcs[oldIndex][newIndex + 1]) {
      oldIndex += 1;
    } else {
      newIndex += 1;
    }
  }
  matches.push([oldParagraphs.length, newParagraphs.length]);

  const hunks = [];
  let previousOld = 0;
  let previousNew = 0;
  for (const [matchedOld, matchedNew] of matches) {
    const removed = oldParagraphs.slice(previousOld, matchedOld);
    const added = newParagraphs.slice(previousNew, matchedNew);
    const paired = Math.min(removed.length, added.length);
    for (let offset = 0; offset < paired; offset += 1) {
      hunks.push({
        type: "replace",
        paragraph_index: previousOld + offset + 1,
        old_text: removed[offset],
        new_text: added[offset],
      });
    }
    for (let offset = paired; offset < removed.length; offset += 1) {
      hunks.push({
        type: "delete",
        paragraph_index: previousOld + offset + 1,
        old_text: removed[offset],
        new_text: "",
      });
    }
    if (added.length > paired) {
      hunks.push({
        type: "insert_after",
        paragraph_index: matchedOld,
        old_text: "",
        new_text: added.slice(paired).join("\n\n"),
      });
    }
    previousOld = matchedOld + 1;
    previousNew = matchedNew + 1;
  }
  return hunks;
}

function summarizeContentDiff(hunks, originalContent, currentContent) {
  return {
    paragraphs_changed: hunks.length,
    chars_added: hunks.reduce((total, hunk) => total + (hunk.new_text || "").length, 0),
    chars_removed: hunks.reduce((total, hunk) => total + (hunk.old_text || "").length, 0),
    content_changed: originalContent !== currentContent,
  };
}

function insertedParagraphs(hunk) {
  return splitParagraphs(hunk.new_text || "");
}

function applySingle(paragraphs, hunk) {
  const type = hunk.type || "replace";
  const idx = hunk.paragraph_index;
  const result = [...paragraphs];

  if (type === "insert_after") {
    const inserted = insertedParagraphs(hunk);
    if (inserted.length) {
      result.splice(idx, 0, ...inserted);
    }
    return result;
  }

  const pos = idx - 1;
  if (type === "replace") {
    const paragraph = result[pos];
    if (hunk.old_text === paragraph) {
      result[pos] = hunk.new_text;
    } else {
      result[pos] = paragraph.replace(hunk.old_text, hunk.new_text);
    }
  } else if (type === "delete") {
    result.splice(pos, 1);
  }
  return result;
}

function reverseSingle(paragraphs, hunk) {
  const type = hunk.type || "replace";
  const idx = hunk.paragraph_index;
  const result = [...paragraphs];

  if (type === "insert_after") {
    const count = insertedParagraphs(hunk).length;
    if (count > 0 && idx >= 0) {
      result.splice(idx, count);
    }
    return result;
  }

  const pos = idx - 1;
  if (pos < 0) return result;
  if (type === "replace") {
    if (pos >= result.length) return result;
    const paragraph = result[pos];
    if (hunk.new_text === paragraph) {
      result[pos] = hunk.old_text;
    } else {
      result[pos] = paragraph.replace(hunk.new_text, hunk.old_text);
    }
  } else if (type === "delete") {
    result.splice(pos, 0, hunk.old_text);
  }
  return result;
}

function sortForApply(hunks) {
  return [...hunks].sort((a, b) => {
    if (b.paragraph_index !== a.paragraph_index) {
      return b.paragraph_index - a.paragraph_index;
    }
    return (TYPE_ORDER[b.type] ?? 3) - (TYPE_ORDER[a.type] ?? 3);
  });
}

function sortForReverse(hunks) {
  return [...hunks].sort((a, b) => {
    if (a.paragraph_index !== b.paragraph_index) {
      return a.paragraph_index - b.paragraph_index;
    }
    return (TYPE_ORDER[a.type] ?? 3) - (TYPE_ORDER[b.type] ?? 3);
  });
}

export function applyHunks(content, hunks) {
  let current = splitParagraphs(content);
  for (const hunk of sortForApply(hunks)) {
    current = applySingle(current, hunk);
  }
  return joinParagraphs(current);
}

export function reverseHunks(content, hunks) {
  let current = splitParagraphs(content);
  for (const hunk of sortForReverse(hunks)) {
    current = reverseSingle(current, hunk);
  }
  return joinParagraphs(current);
}

export function stillAppliedHunks(hunks) {
  return (hunks || []).filter((hunk) => hunk.status !== "rejected");
}

export function pendingHunks(hunks) {
  return (hunks || []).filter((hunk) => !hunk.status);
}

export function contentAfterDecisions(originalContent, hunks) {
  return applyHunks(originalContent, stillAppliedHunks(hunks));
}

export function setHunkStatus(hunks, hunkIndex, status) {
  return hunks.map((hunk, index) => (
    index === hunkIndex ? { ...hunk, status } : hunk
  ));
}

export function setAllHunkStatus(hunks, status) {
  return hunks.map((hunk) => (
    hunk.status ? hunk : { ...hunk, status }
  ));
}

export function pendingHunksFromBatches(batches) {
  return (batches || []).flatMap((batch) => pendingHunks(batch.hunks));
}

export function getDiffBatches(diff) {
  if (!diff) return [];
  if (Array.isArray(diff.batches) && diff.batches.length) return diff.batches;
  if (diff.hunks?.length) {
    return [{ original_content: diff.original_content, hunks: diff.hunks }];
  }
  return [];
}

export function recomputeBatchOriginals(batches, baseline) {
  let content = baseline || "";
  return (batches || []).map((batch) => {
    const next = { ...batch, original_content: content };
    content = contentAfterDecisions(content, batch.hunks || []);
    return next;
  });
}

export function contentAfterBatches(batches) {
  if (!batches?.length) return "";
  const hydrated = recomputeBatchOriginals(batches, batches[0].original_content || "");
  const last = hydrated[hydrated.length - 1];
  return contentAfterDecisions(last.original_content, last.hunks || []);
}

export function setHunkStatusInBatches(batches, batchIndex, hunkIndex, status) {
  return (batches || []).map((batch, index) => (
    index === batchIndex
      ? { ...batch, hunks: setHunkStatus(batch.hunks || [], hunkIndex, status) }
      : batch
  ));
}

export function setAllHunkStatusInBatches(batches, status) {
  return (batches || []).map((batch) => ({
    ...batch,
    hunks: setAllHunkStatus(batch.hunks || [], status),
  }));
}

export function hydrateDiffBatches(currentContent, diff) {
  const batches = getDiffBatches(diff);
  if (!batches.length) {
    return { ...diff, original_content: currentContent || "", batches: [] };
  }
  const knownOriginal = diff?.original_content != null
    ? diff.original_content
    : batches[0]?.original_content;
  let baseline;
  if (knownOriginal != null) {
    baseline = knownOriginal;
  } else {
    baseline = currentContent || "";
    for (let index = batches.length - 1; index >= 0; index -= 1) {
      baseline = reverseHunks(baseline, stillAppliedHunks(batches[index].hunks));
    }
  }
  const hydrated = recomputeBatchOriginals(batches, baseline);
  return {
    ...diff,
    original_content: baseline,
    batches: hydrated,
  };
}

export function accumulateNodeContentDiff(existing, incoming, currentContent) {
  if (!incoming) return null;
  const incomingHunks = incoming.hunks || [];
  const existingBatches = getDiffBatches(existing);

  if (!incomingHunks.length) {
    return existing || incoming;
  }

  const incomingOriginal = incoming.original_content;
  const incomingCurrent = incoming.current_content ?? currentContent;
  const existingOriginal = existing?.original_content;
  const acceptedExistingHunks = getDiffBatches(existing)
    .flatMap((batch) => batch.hunks || [])
    .filter((hunk) => hunk.status === "accepted");
  const baseline = existingOriginal != null
    ? applyHunks(existingOriginal, acceptedExistingHunks)
    : incomingOriginal;
  if (baseline != null && incomingCurrent != null) {
    const netHunks = buildContentDiffFromContents(baseline, incomingCurrent);
    return {
      ...existing,
      ...incoming,
      original_content: baseline,
      current_content: incomingCurrent,
      hunks: netHunks,
      summary: summarizeContentDiff(netHunks, baseline, incomingCurrent),
      batches: [{ original_content: baseline, hunks: netHunks }],
    };
  }

  if (!existingBatches.length) {
    let original = incoming.original_content;
    if (original == null && currentContent != null && incomingHunks.length) {
      original = reverseHunks(currentContent, incomingHunks);
    }
    return {
      ...incoming,
      original_content: original,
      batches: [{ original_content: original, hunks: incomingHunks }],
    };
  }

  const legacyBaseline = existing.original_content ?? existingBatches[0].original_content;
  const batchOriginal = legacyBaseline == null
    ? undefined
    : contentAfterBatches(existingBatches);
  return {
    ...existing,
    ...incoming,
    original_content: legacyBaseline,
    batches: [
      ...existingBatches,
      { original_content: batchOriginal, hunks: incomingHunks },
    ],
  };
}

function appliedTextOfHunk(hunk) {
  if (hunk.status === "rejected") {
    if ((hunk.type || "replace") === "insert_after") return null;
    return hunk.old_text || "";
  }
  if ((hunk.type || "replace") === "delete") return null;
  return hunk.new_text || "";
}

function overlayBatch(slots, hunks, batchIndex) {
  const occupying = slots.filter((slot) => slot.appliedText != null);
  const nextSlots = [];

  const pushInserts = (paragraphIndex) => {
    for (const item of hunksAt(hunks, paragraphIndex, (type) => type === "insert_after")) {
      if (item.hunk.status === "rejected") continue;
      const appliedText = appliedTextOfHunk(item.hunk);
      if (item.hunk.status === "accepted") {
        nextSlots.push({
          appliedText,
          blocks: [{ kind: "paragraph", text: appliedText }],
        });
        continue;
      }
      nextSlots.push({
        appliedText,
        blocks: [{ kind: "hunk", hunk: item.hunk, hunkIndex: item.index, batchIndex }],
      });
    }
  };

  pushInserts(0);

  occupying.forEach((slot, offset) => {
    const paragraphIndex = offset + 1;
    const edits = hunksAt(hunks, paragraphIndex, (type) => type !== "insert_after");
    const edit = edits[0];

    if (!edit) {
      nextSlots.push(slot);
    } else if (edit.hunk.status === "accepted") {
      if (edit.hunk.type !== "delete") {
        const earlierHunks = slot.blocks.filter((block) => block.kind === "hunk");
        nextSlots.push({
          appliedText: appliedTextOfHunk(edit.hunk),
          blocks: earlierHunks.length
            ? earlierHunks
            : [{ kind: "paragraph", text: appliedTextOfHunk(edit.hunk), paragraphIndex }],
        });
      } else {
        const earlierHunks = slot.blocks.filter((block) => block.kind === "hunk");
        if (earlierHunks.length) {
          nextSlots.push({ appliedText: null, blocks: earlierHunks });
        }
      }
    } else if (edit.hunk.status === "rejected") {
      nextSlots.push(slot);
    } else {
      const earlierHunks = slot.blocks.filter((block) => block.kind === "hunk");
      nextSlots.push({
        appliedText: appliedTextOfHunk(edit.hunk),
        blocks: [
          ...earlierHunks,
          { kind: "hunk", hunk: edit.hunk, hunkIndex: edit.index, batchIndex, paragraph: slot.appliedText },
        ],
      });
    }

    pushInserts(paragraphIndex);
  });

  return nextSlots;
}

export function buildStackedInlineDiffBlocks(batches) {
  if (!batches?.length) return [];
  const baseline = batches[0].original_content || "";
  let slots = splitParagraphs(baseline).map((text) => ({
    appliedText: text,
    blocks: [{ kind: "paragraph", text, paragraphIndex: undefined }],
  }));
  batches.forEach((batch, batchIndex) => {
    slots = overlayBatch(slots, batch.hunks || [], batchIndex);
  });
  return slots.flatMap((slot) => slot.blocks);
}

function hunksAt(hunks, paragraphIndex, typeFilter) {
  return hunks
    .map((hunk, index) => ({ hunk, index }))
    .filter(({ hunk }) => hunk.paragraph_index === paragraphIndex && typeFilter(hunk.type || "replace"));
}

function blockForSettledReplace(paragraph, hunk) {
  if (hunk.old_text === paragraph) return hunk.new_text;
  return paragraph.replace(hunk.old_text, hunk.new_text);
}

export function buildInlineDiffBlocks(originalContent, hunks) {
  const paragraphs = splitParagraphs(originalContent);
  const blocks = [];

  const pushInserts = (paragraphIndex) => {
    for (const item of hunksAt(hunks, paragraphIndex, (type) => type === "insert_after")) {
      if (item.hunk.status === "rejected") continue;
      if (item.hunk.status === "accepted") {
        blocks.push({ kind: "paragraph", text: item.hunk.new_text });
        continue;
      }
      blocks.push({ kind: "hunk", hunk: item.hunk, hunkIndex: item.index });
    }
  };

  pushInserts(0);

  paragraphs.forEach((paragraph, offset) => {
    const paragraphIndex = offset + 1;
    const edits = hunksAt(hunks, paragraphIndex, (type) => type !== "insert_after");
    const edit = edits[0];

    if (!edit) {
      blocks.push({ kind: "paragraph", text: paragraph, paragraphIndex });
    } else if (edit.hunk.status === "accepted") {
      if (edit.hunk.type !== "delete") {
        blocks.push({
          kind: "paragraph",
          text: blockForSettledReplace(paragraph, edit.hunk),
          paragraphIndex,
        });
      }
    } else if (edit.hunk.status === "rejected") {
      blocks.push({ kind: "paragraph", text: paragraph, paragraphIndex });
    } else {
      blocks.push({ kind: "hunk", hunk: edit.hunk, hunkIndex: edit.index, paragraph });
    }

    pushInserts(paragraphIndex);
  });

  return blocks;
}
