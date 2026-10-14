const TYPE_ORDER = { delete: 0, replace: 1, insert_after: 2 };
import { applyAgentGroups } from "./agentContentDiff";

function graphemes(value) {
  return Array.from(value || "");
}

function tokenOperations(oldTokens, newTokens) {
  const frontier = new Map([[1, 0]]);
  const trace = [];
  const maxDistance = oldTokens.length + newTokens.length;

  for (let distance = 0; distance <= maxDistance; distance += 1) {
    trace.push(new Map(frontier));
    for (let diagonal = -distance; diagonal <= distance; diagonal += 2) {
      const fromDelete = frontier.get(diagonal - 1) ?? Number.NEGATIVE_INFINITY;
      const fromInsert = frontier.get(diagonal + 1) ?? Number.NEGATIVE_INFINITY;
      let oldIndex = diagonal === -distance || (diagonal !== distance && fromDelete < fromInsert)
        ? fromInsert
        : fromDelete + 1;
      let newIndex = oldIndex - diagonal;
      while (oldIndex < oldTokens.length && newIndex < newTokens.length
        && oldTokens[oldIndex] === newTokens[newIndex]) {
        oldIndex += 1;
        newIndex += 1;
      }
      frontier.set(diagonal, oldIndex);
      if (oldIndex < oldTokens.length || newIndex < newTokens.length) continue;

      const reversed = [];
      let backOld = oldTokens.length;
      let backNew = newTokens.length;
      for (let backDistance = trace.length - 1; backDistance >= 0; backDistance -= 1) {
        const previous = trace[backDistance];
        const backDiagonal = backOld - backNew;
        const previousDelete = previous.get(backDiagonal - 1) ?? Number.NEGATIVE_INFINITY;
        const previousInsert = previous.get(backDiagonal + 1) ?? Number.NEGATIVE_INFINITY;
        const previousDiagonal = backDiagonal === -backDistance
          || (backDiagonal !== backDistance && previousDelete < previousInsert)
          ? backDiagonal + 1
          : backDiagonal - 1;
        const previousOld = previous.get(previousDiagonal) ?? 0;
        const previousNew = previousOld - previousDiagonal;

        while (backOld > previousOld && backNew > previousNew) {
          reversed.push({ kind: "equal", text: oldTokens[backOld - 1] });
          backOld -= 1;
          backNew -= 1;
        }
        if (backDistance === 0) break;
        if (backOld === previousOld) {
          reversed.push({ kind: "insert", text: newTokens[backNew - 1] });
          backNew -= 1;
        } else {
          reversed.push({ kind: "delete", text: oldTokens[backOld - 1] });
          backOld -= 1;
        }
      }
      return reversed.reverse();
    }
  }
  return [];
}

function alignedBoundaryMap(baselineCharacters, currentCharacters) {
  const operations = tokenOperations(baselineCharacters, currentCharacters);
  const boundaries = Array(currentCharacters.length + 1);
  let baselineIndex = 0;
  let currentIndex = 0;
  let operationIndex = 0;

  while (operationIndex < operations.length) {
    if (operations[operationIndex].kind === "equal") {
      boundaries[currentIndex] = baselineIndex;
      baselineIndex += 1;
      currentIndex += 1;
      boundaries[currentIndex] = baselineIndex;
      operationIndex += 1;
      continue;
    }

    const baselineStart = baselineIndex;
    const currentStart = currentIndex;
    while (operationIndex < operations.length && operations[operationIndex].kind !== "equal") {
      if (operations[operationIndex].kind === "delete") baselineIndex += 1;
      else currentIndex += 1;
      operationIndex += 1;
    }
    const baselineLength = baselineIndex - baselineStart;
    const currentLength = currentIndex - currentStart;
    if (currentLength === 0) {
      boundaries[currentStart] = baselineIndex;
      continue;
    }
    for (let offset = 0; offset <= currentLength; offset += 1) {
      boundaries[currentStart + offset] = baselineStart
        + Math.round((baselineLength * offset) / currentLength);
    }
  }

  boundaries[0] ??= 0;
  boundaries[currentCharacters.length] ??= baselineCharacters.length;
  return boundaries;
}

function textEditBlocks(currentCharacters, editedCharacters) {
  const operations = tokenOperations(currentCharacters, editedCharacters);
  const blocks = [];
  let currentIndex = 0;
  let operationIndex = 0;

  while (operationIndex < operations.length) {
    if (operations[operationIndex].kind === "equal") {
      currentIndex += 1;
      operationIndex += 1;
      continue;
    }

    const start = currentIndex;
    const replacement = [];
    while (operationIndex < operations.length && operations[operationIndex].kind !== "equal") {
      const operation = operations[operationIndex];
      if (operation.kind === "delete") currentIndex += 1;
      else replacement.push(operation.text);
      operationIndex += 1;
    }
    blocks.push({ start, end: currentIndex, replacement });
  }
  return blocks;
}

export function commitUserTextEdit(baselineText, currentText, editedText) {
  const baselineCharacters = graphemes(baselineText);
  const currentCharacters = graphemes(currentText);
  const editedCharacters = graphemes(editedText);
  const boundaries = alignedBoundaryMap(baselineCharacters, currentCharacters);
  const blocks = textEditBlocks(currentCharacters, editedCharacters);

  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    const baselineStart = boundaries[block.start];
    const baselineEnd = boundaries[block.end];
    baselineCharacters.splice(
      baselineStart,
      baselineEnd - baselineStart,
      ...block.replacement,
    );
  }

  return {
    baselineText: baselineCharacters.join(""),
    currentText: editedText,
  };
}

export function splitParagraphs(content) {
  const text = content || "";
  if (!text) return [];
  return text.split("\n\n");
}

export function joinParagraphs(paragraphs) {
  return paragraphs.join("\n\n");
}

function comparableCharacters(text) {
  return graphemes(text)
    .filter((character) => /[\p{L}\p{N}]/u.test(character))
    .map((character) => character.toLocaleLowerCase());
}

function multisetDice(left, right) {
  if (!left.length || !right.length) return 0;
  const counts = new Map();
  for (const item of left) counts.set(item, (counts.get(item) || 0) + 1);
  let overlap = 0;
  for (const item of right) {
    const remaining = counts.get(item) || 0;
    if (remaining > 0) {
      overlap += 1;
      counts.set(item, remaining - 1);
    }
  }
  return (2 * overlap) / (left.length + right.length);
}

function characterPairs(characters) {
  const pairs = [];
  for (let index = 1; index < characters.length; index += 1) {
    pairs.push(`${characters[index - 1]}\u0000${characters[index]}`);
  }
  return pairs;
}

function paragraphFeatures(text) {
  const characters = comparableCharacters(text);
  return { characters, pairs: characterPairs(characters) };
}

function paragraphSimilarity(oldText, newText, oldFeatures, newFeatures) {
  if (oldText === newText) return 1;
  const oldCharacters = oldFeatures.characters;
  const newCharacters = newFeatures.characters;
  if (!oldCharacters.length || !newCharacters.length) return 0;
  const characterScore = multisetDice(oldCharacters, newCharacters);
  const oldPairs = oldFeatures.pairs;
  const newPairs = newFeatures.pairs;
  const pairScore = oldPairs.length && newPairs.length ? multisetDice(oldPairs, newPairs) : characterScore;
  return (characterScore * 0.7) + (pairScore * 0.3);
}

function alignParagraphs(oldParagraphs, newParagraphs) {
  const rows = oldParagraphs.length + 1;
  const cols = newParagraphs.length + 1;
  const matrix = Array.from({ length: rows }, () => Array(cols));
  const oldFeatures = oldParagraphs.map(paragraphFeatures);
  const newFeatures = newParagraphs.map(paragraphFeatures);
  matrix[0][0] = { cost: 0, operation: null };
  for (let oldIndex = 1; oldIndex < rows; oldIndex += 1) {
    matrix[oldIndex][0] = { cost: oldIndex, operation: "delete" };
  }
  for (let newIndex = 1; newIndex < cols; newIndex += 1) {
    matrix[0][newIndex] = { cost: newIndex, operation: "insert" };
  }

  for (let oldIndex = 1; oldIndex < rows; oldIndex += 1) {
    for (let newIndex = 1; newIndex < cols; newIndex += 1) {
      const oldText = oldParagraphs[oldIndex - 1];
      const newText = newParagraphs[newIndex - 1];
      const candidates = [];
      if (oldText === newText) {
        candidates.push({
          cost: matrix[oldIndex - 1][newIndex - 1].cost,
          operation: "equal",
        });
      } else {
        const similarity = paragraphSimilarity(
          oldText,
          newText,
          oldFeatures[oldIndex - 1],
          newFeatures[newIndex - 1],
        );
        if (similarity >= 0.45) {
          candidates.push({
            cost: matrix[oldIndex - 1][newIndex - 1].cost + (2 * (1 - similarity)),
            operation: "replace",
          });
        }
      }
      candidates.push({ cost: matrix[oldIndex][newIndex - 1].cost + 1, operation: "insert" });
      candidates.push({ cost: matrix[oldIndex - 1][newIndex].cost + 1, operation: "delete" });
      matrix[oldIndex][newIndex] = candidates.reduce((best, candidate) => (
        candidate.cost < best.cost ? candidate : best
      ));
    }
  }

  const reversed = [];
  let oldIndex = oldParagraphs.length;
  let newIndex = newParagraphs.length;
  while (oldIndex > 0 || newIndex > 0) {
    const operation = matrix[oldIndex][newIndex].operation;
    if (operation === "equal" || operation === "replace") {
      reversed.push({
        operation,
        oldText: oldParagraphs[oldIndex - 1],
        newText: newParagraphs[newIndex - 1],
      });
      oldIndex -= 1;
      newIndex -= 1;
    } else if (operation === "delete") {
      reversed.push({ operation, oldText: oldParagraphs[oldIndex - 1] });
      oldIndex -= 1;
    } else {
      reversed.push({ operation: "insert", newText: newParagraphs[newIndex - 1] });
      newIndex -= 1;
    }
  }
  return reversed.reverse();
}

export function buildContentDiffFromContents(originalContent, currentContent) {
  if (originalContent === currentContent) return [];
  const oldParagraphs = splitParagraphs(originalContent);
  const newParagraphs = splitParagraphs(currentContent);
  let commonPrefixLength = 0;
  while (
    commonPrefixLength < oldParagraphs.length
    && commonPrefixLength < newParagraphs.length
    && oldParagraphs[commonPrefixLength] === newParagraphs[commonPrefixLength]
  ) {
    commonPrefixLength += 1;
  }

  let oldChangedEnd = oldParagraphs.length;
  let newChangedEnd = newParagraphs.length;
  while (
    oldChangedEnd > commonPrefixLength
    && newChangedEnd > commonPrefixLength
    && oldParagraphs[oldChangedEnd - 1] === newParagraphs[newChangedEnd - 1]
  ) {
    oldChangedEnd -= 1;
    newChangedEnd -= 1;
  }

  const operations = alignParagraphs(
    oldParagraphs.slice(commonPrefixLength, oldChangedEnd),
    newParagraphs.slice(commonPrefixLength, newChangedEnd),
  );
  const hunks = [];
  let oldParagraphIndex = commonPrefixLength;

  for (let index = 0; index < operations.length; index += 1) {
    const operation = operations[index];
    if (operation.operation === "equal") {
      oldParagraphIndex += 1;
    } else if (operation.operation === "replace") {
      oldParagraphIndex += 1;
      hunks.push({
        type: "replace",
        paragraph_index: oldParagraphIndex,
        old_text: operation.oldText,
        new_text: operation.newText,
      });
    } else if (operation.operation === "delete") {
      oldParagraphIndex += 1;
      hunks.push({
        type: "delete",
        paragraph_index: oldParagraphIndex,
        old_text: operation.oldText,
        new_text: "",
      });
    } else {
      const inserted = [operation.newText];
      while (operations[index + 1]?.operation === "insert") {
        index += 1;
        inserted.push(operations[index].newText);
      }
      hunks.push({
        type: "insert_after",
        paragraph_index: oldParagraphIndex,
        old_text: "",
        new_text: joinParagraphs(inserted),
      });
    }
  }
  return hunks;
}

export function commitUserParagraphEdit(baselineContent, currentContent, paragraphIndex, nextText) {
  const baselineParagraphs = splitParagraphs(baselineContent);
  const currentParagraphs = splitParagraphs(currentContent);
  const operations = alignParagraphs(baselineParagraphs, currentParagraphs);
  const targetNewIndex = paragraphIndex - 1;
  let oldIndex = 0;
  let newIndex = 0;

  for (const operation of operations) {
    if (operation.operation === "delete") {
      oldIndex += 1;
      continue;
    }
    if (newIndex !== targetNewIndex) {
      if (operation.operation !== "insert") oldIndex += 1;
      newIndex += 1;
      continue;
    }

    currentParagraphs[newIndex] = nextText;
    if (operation.operation === "insert") baselineParagraphs.splice(oldIndex, 0, nextText);
    else baselineParagraphs[oldIndex] = nextText;
    return {
      baselineContent: joinParagraphs(baselineParagraphs),
      currentContent: joinParagraphs(currentParagraphs),
    };
  }

  throw new RangeError(`Paragraph ${paragraphIndex} does not exist in current content`);
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
  if (hunks.length && hunks.every((hunk) => hunk.start_offset != null)) {
    return applyAgentGroups(content, [...hunks].sort((a, b) => a.start_offset - b.start_offset));
  }
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
  if (diff.grouping === "agent_replacements") {
    return diff.hunks?.length ? [{ grouping: diff.grouping, original_content: diff.original_content, hunks: diff.hunks }] : [];
  }
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
  if (incoming.grouping === "agent_replacements") {
    return { ...incoming, batches: getDiffBatches(incoming) };
  }
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
  const baseline = incoming.baseline_content != null
    ? incoming.baseline_content
    : existingOriginal != null
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

function indexHunksByParagraph(hunks) {
  const edits = new Map();
  const inserts = new Map();
  (hunks || []).forEach((hunk, index) => {
    const item = { hunk, index };
    const target = (hunk.type || "replace") === "insert_after" ? inserts : edits;
    const paragraphIndex = hunk.paragraph_index;
    const items = target.get(paragraphIndex);
    if (items) items.push(item);
    else target.set(paragraphIndex, [item]);
  });
  return { edits, inserts };
}

function overlayBatch(slots, hunks, batchIndex) {
  const occupying = slots.filter((slot) => slot.appliedText != null);
  const nextSlots = [];
  const hunkIndex = indexHunksByParagraph(hunks);

  const pushInserts = (paragraphIndex) => {
    for (const item of hunkIndex.inserts.get(paragraphIndex) || []) {
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
    const edits = hunkIndex.edits.get(paragraphIndex) || [];
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

function blockForSettledReplace(paragraph, hunk) {
  if (hunk.old_text === paragraph) return hunk.new_text;
  return paragraph.replace(hunk.old_text, hunk.new_text);
}

export function buildInlineDiffBlocks(originalContent, hunks) {
  const paragraphs = splitParagraphs(originalContent);
  const blocks = [];
  const hunkIndex = indexHunksByParagraph(hunks);

  const pushInserts = (paragraphIndex) => {
    for (const item of hunkIndex.inserts.get(paragraphIndex) || []) {
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
    const edits = hunkIndex.edits.get(paragraphIndex) || [];
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
