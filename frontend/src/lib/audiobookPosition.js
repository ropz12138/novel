import { splitAudiobookLines } from "./audiobook";

const positionKey = (workId, nodeId) => `novel:audiobookPosition:${JSON.stringify([workId, nodeId])}`;

export function readAudiobookPosition(workId, nodeId, content) {
  try {
    const key = positionKey(workId, nodeId);
    const saved = JSON.parse(localStorage.getItem(key));
    if (!saved) return 0;
    const lines = splitAudiobookLines(content || "");
    if (Number.isInteger(saved.lineIndex) && saved.lineIndex >= 0 && lines[saved.lineIndex] === saved.lineText) {
      return saved.lineIndex;
    }
    localStorage.removeItem(key);
  } catch { /* Storage may be unavailable; playback can still start normally. */ }
  return 0;
}

export function saveAudiobookPosition(workId, nodeId, lineIndex, lineText) {
  try {
    localStorage.setItem(positionKey(workId, nodeId), JSON.stringify({ lineIndex, lineText }));
  } catch { /* A storage failure must not interrupt audio playback. */ }
}

export function clearAudiobookPosition(workId, nodeId) {
  try {
    localStorage.removeItem(positionKey(workId, nodeId));
  } catch { /* Playback completion does not depend on storage availability. */ }
}
