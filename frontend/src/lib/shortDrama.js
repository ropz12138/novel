export function chapterDramaPath(workId, chapterId) {
  return `/short-drama/${encodeURIComponent(workId)}/${encodeURIComponent(chapterId)}`;
}

export function createShot() {
  return {
    id: crypto.randomUUID(), title: '', prompt: '', duration: 5, seed: 42,
    mode: 'turbo', inputMode: 'text', roles: [], sourceQuote: '',
    referencePaths: '', firstFrame: '', lastFrame: '', firstFrameShotId: '', sourceStartLine: null, sourceEndLine: null,
  };
}

export function formatDramaDuration(seconds) {
  const total = Math.round(seconds * 100) / 100;
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  const remainder = Math.round((total - minutes * 60) * 100) / 100;
  return `${minutes} 分 ${remainder} 秒（${total} 秒）`;
}

export function resolveInputMode(shot) {
  const hasSource = Boolean(shot.firstFrameShotId);
  const hasReference = (shot.roles || []).some((role) => role.portraitId);
  if (hasSource && hasReference) return 'conflict';
  if (hasSource) return 'first_lock';
  if (hasReference) return 'reference';
  return 'text';
}

export function buildGenerationRequests(draft) {
  return draft.shots.map((shot) => ({
    shot_id: shot.id,
    prompt: shot.prompt,
    duration: Number(shot.duration),
    width: Number(draft.width), height: Number(draft.height),
    seed: Number(shot.seed), turbo: shot.mode === 'turbo',
    steps: shot.mode === 'turbo' ? 8 : 20,
    reference_images: resolveInputMode(shot) === 'reference'
      ? [...shot.roles].sort((a, b) => a.roleId.localeCompare(b.roleId)).filter(role => role.portraitId).map(role => draft.portraits.find(portrait => portrait.id === role.portraitId)?.imagePath).filter(Boolean) : [],
    first_frame: null,
    last_frame: null,
    output_path: `outputs/short_drama/${shot.id}.mp4`,
  }));
}

function readJsonString(raw, start) {
  let value = '';
  let index = start + 1;
  while (index < raw.length) {
    const char = raw[index];
    if (char === '\\') {
      if (index + 1 >= raw.length) return { value, closed: false, next: raw.length };
      const next = raw[index + 1];
      if (next === 'u') {
        if (index + 5 >= raw.length) return { value, closed: false, next: raw.length };
        value += String.fromCharCode(Number.parseInt(raw.slice(index + 2, index + 6), 16));
        index += 6;
        continue;
      }
      const escaped = { n: '\n', r: '\r', t: '\t', '"': '"', '\\': '\\', '/': '/' };
      value += escaped[next] ?? next;
      index += 2;
      continue;
    }
    if (char === '"') return { value, closed: true, next: index + 1 };
    value += char;
    index += 1;
  }
  return { value, closed: false, next: raw.length };
}

function assignStoryboardString(preview, parent, value) {
  const key = parent.pendingKey;
  if (parent.role && (key === 'roleId' || key === 'portraitId')) parent.role[key] = value;
  else if (parent.shot && (key === 'id' || key === 'title' || key === 'prompt' || key === 'sourceQuote')) parent.shot[key] = value;
  if (!parent.shot && key === 'message') preview.message = value;
}

export function previewStoryboardArguments(raw) {
  const preview = { message: '', shots: [] };
  if (!raw) return preview;
  const stack = [];
  let index = 0;
  const top = () => stack[stack.length - 1] || null;
  while (index < raw.length) {
    const char = raw[index];
    if (char === '{') {
      const parent = top();
      if (parent?.kind === 'array' && parent.key === 'roles' && parent.shot) {
        const role = { roleId: '', portraitId: null };
        parent.shot.roles.push(role);
        stack.push({ kind: 'object', expect: 'key', pendingKey: null, shot: parent.shot, role });
        index += 1;
        continue;
      }
      let shot = parent?.shot || null;
      if (parent?.kind === 'array' && (parent.key === 'shots' || parent.key === 'updates')) {
        shot = { title: '', prompt: '', sourceQuote: '', duration: null, roles: [] };
        preview.shots.push(shot);
      }
      stack.push({ kind: 'object', expect: 'key', pendingKey: null, shot });
      if (parent?.kind === 'object') parent.pendingKey = null;
      index += 1;
      continue;
    }
    if (char === '[') {
      const parent = top();
      stack.push({ kind: 'array', key: parent?.kind === 'object' ? parent.pendingKey : null, expect: 'value', shot: parent?.shot || null });
      if (parent?.kind === 'object') parent.pendingKey = null;
      index += 1;
      continue;
    }
    if (char === '}' || char === ']') {
      stack.pop();
      const parent = top();
      if (parent) parent.expect = 'comma';
      index += 1;
      continue;
    }
    if (char === ':') {
      const parent = top();
      if (parent?.kind === 'object') parent.expect = 'value';
      index += 1;
      continue;
    }
    if (char === ',') {
      const parent = top();
      if (parent?.kind === 'object') parent.expect = 'key';
      else if (parent?.kind === 'array') parent.expect = 'value';
      index += 1;
      continue;
    }
    if (char === '"') {
      const read = readJsonString(raw, index);
      const parent = top();
      if (parent?.kind === 'object' && parent.expect === 'key') {
        parent.pendingKey = read.value;
        if (read.closed) parent.expect = 'colon';
      } else if (parent?.kind === 'object' && parent.expect === 'value') {
        assignStoryboardString(preview, parent, read.value);
        if (read.closed) parent.expect = 'comma';
      } else if (parent?.kind === 'array' && parent.key === 'roleIds' && parent.shot && read.closed) {
        parent.shot.roles.push({ roleId: read.value, portraitId: null });
        parent.expect = 'comma';
      }
      index = read.next;
      if (!read.closed) break;
      continue;
    }
    const literal = /^(null|true|false)/.exec(raw.slice(index));
    if (literal && top()?.expect === 'value') {
      const parent = top();
      if (parent.role && parent.pendingKey === 'portraitId' && literal[1] === 'null') parent.role.portraitId = null;
      parent.pendingKey = null;
      parent.expect = 'comma';
      index += literal[1].length;
      continue;
    }
    if (char === '-' || (char >= '0' && char <= '9')) {
      const match = /^-?\d+(?:\.\d+)?/.exec(raw.slice(index));
      const parent = top();
      if (match && parent?.kind === 'object' && parent.expect === 'value') {
        if (parent.shot && parent.pendingKey === 'duration') parent.shot.duration = Number(match[0]);
        parent.pendingKey = null;
        parent.expect = 'comma';
        index += match[0].length;
        continue;
      }
    }
    index += 1;
  }
  return preview;
}

function pythonRound(value, digits = 0) {
  const factor = 10 ** digits;
  const scaled = value * factor;
  const negative = scaled < 0;
  const abs = Math.abs(scaled);
  const base = Math.floor(abs);
  const fraction = abs - base;
  const rounded = fraction > 0.5 || (fraction === 0.5 && base % 2 === 1) ? base + 1 : base;
  const result = rounded / factor;
  return negative ? -result : result;
}

export function videoTiming(duration) {
  const n = Math.max(1, pythonRound((duration * 24 - 5) / 17));
  const frames = 17 * n + 5;
  return { frames, actualDuration: pythonRound(frames / 24, 3) };
}
