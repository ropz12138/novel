import { useCallback, useEffect, useRef, useState } from 'react';
import { getDramaWorkspace, saveDramaWorkspace, saveDramaPortraits, listDramaSessions, createDramaSession, getDramaSession } from '../lib/shortDramaApi';

export function boardFields(draft) {
  return { sourceContent: draft.sourceContent, width: draft.width, height: draft.height, style: draft.style,
    shots: draft.shots };
}

export function useDramaWorkspace(workId, chapterId) {
  const [draft, setDraftState] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [saveError, setSaveError] = useState('');
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const stateRef = useRef(null);
  const savedRef = useRef('');
  const savedPortraitsRef = useRef('');
  const revisionRef = useRef(0);
  const portraitRevisionRef = useRef(0);
  const saveRef = useRef(null);
  const loadRef = useRef(0);
  const preferenceKey = `novel.drama.session:${localStorage.getItem('novel_user')}:${workId}`;

  const replaceBoard = useCallback((board) => {
    revisionRef.current = board.revision;
    portraitRevisionRef.current = board.portraitRevision;
    savedRef.current = JSON.stringify(boardFields(board));
    savedPortraitsRef.current = JSON.stringify(board.portraits);
    setDraftState(current => {
      const next = { ...board, conversationDraft: current?.conversationDraft || '' };
      stateRef.current = next;
      return next;
    });
  }, []);
  const setDraft = useCallback((value) => {
    setDraftState(current => {
      const next = typeof value === 'function' ? value(current) : value;
      stateRef.current = next;
      return next;
    });
  }, []);
  const replacePortraits = useCallback((board) => {
    portraitRevisionRef.current = board.portraitRevision;
    savedPortraitsRef.current = JSON.stringify(board.portraits);
    setDraft(current => ({ ...current, portraits: board.portraits, portraitRevision: board.portraitRevision }));
  }, [setDraft]);
  const refreshSessions = useCallback(async () => {
    const rows = await listDramaSessions(workId, chapterId);
    setSessions(rows);
    return rows;
  }, [workId, chapterId]);

  const flush = useCallback(async () => {
    if (saveRef.current) await saveRef.current;
    const state = stateRef.current;
    if (!state) return;
    const fields = boardFields(state);
    const signature = JSON.stringify(fields);
    const portraitSignature = JSON.stringify(state.portraits);
    if (signature === savedRef.current && portraitSignature === savedPortraitsRef.current) return;
    setSaving(true);
    const save = Promise.resolve()
      .then(async () => {
        if (portraitSignature !== savedPortraitsRef.current) {
          const saved = await saveDramaPortraits(workId, { revision: portraitRevisionRef.current, portraits: state.portraits });
          portraitRevisionRef.current = saved.portraitRevision;
          savedPortraitsRef.current = portraitSignature;
        }
        if (signature !== savedRef.current) {
          const board = await saveDramaWorkspace(workId, chapterId, { ...fields, revision: revisionRef.current });
          revisionRef.current = board.revision;
          savedRef.current = signature;
        }
        setSaveError('');
      }).catch(err => { setSaveError(err.message); throw err; })
      .finally(() => { saveRef.current = null; setSaving(false); });
    saveRef.current = save;
    await save;
  }, [workId, chapterId]);

  const loadSession = useCallback(async (id) => {
    const generation = ++loadRef.current;
    setLoading(true);
    try {
      const detail = await getDramaSession(workId, chapterId, id);
      if (generation !== loadRef.current) return null;
      replaceBoard(detail.workspace);
      setMessages(detail.messages);
      setSessionId(id);
      setDraft(current => ({ ...current, conversationDraft: '' }));
      localStorage.setItem(preferenceKey, id);
      return detail;
    } finally {
      if (generation === loadRef.current) setLoading(false);
    }
  }, [workId, chapterId, preferenceKey, replaceBoard, setDraft]);

  const initialize = useCallback(async () => {
    const [board, rows] = await Promise.all([getDramaWorkspace(workId, chapterId), refreshSessions()]);
    replaceBoard(board);
    let selected;
    if (rows.length) selected = rows.find(row => row.id === localStorage.getItem(preferenceKey)) || rows[0];
    else { selected = await createDramaSession(workId, chapterId); await refreshSessions(); }
    return loadSession(selected.id);
  }, [workId, chapterId, preferenceKey, refreshSessions, replaceBoard, loadSession]);

  useEffect(() => {
    if (!draft || loading || draft.activeSessionId) return;
    if (JSON.stringify(boardFields(draft)) === savedRef.current) return;
    const timer = setTimeout(() => { flush().catch(() => {}); }, 600);
    return () => clearTimeout(timer);
  }, [draft, loading, flush]);
  useEffect(() => () => { loadRef.current += 1; flush().catch(() => {}); }, [flush]);

  const newSession = async () => {
    setLoading(true);
    try {
      await flush();
      const row = await createDramaSession(workId, chapterId);
      await refreshSessions();
      return await loadSession(row.id);
    } finally { setLoading(false); }
  };
  return { draft, setDraft, sessions, sessionId, messages, setMessages, saving, saveError, loading,
    initialize, loadSession, newSession, flush, replaceBoard, replacePortraits, refreshSessions,
    dirty: Boolean(draft && (JSON.stringify(boardFields(draft)) !== savedRef.current || JSON.stringify(draft.portraits) !== savedPortraitsRef.current)) };
}
