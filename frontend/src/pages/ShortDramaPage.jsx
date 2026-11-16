import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowDown, ArrowUp, BookOpen, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clapperboard, Download, Link2, Maximize2, MoreHorizontal, Plus, Quote, Send, Settings2, Sparkles, Trash2, Users, X } from 'lucide-react';
import { fetchNodes } from '../lib/canvasApi';
import { buildGenerationRequests, createShot, formatDramaDuration, resolveInputMode, videoTiming } from '../lib/shortDrama';
import { sendStoryboardMessage, resumeStoryboardSession, listDramaVideos, generateDramaVideos, deleteDramaVideo, fetchDramaVideo, fetchDramaPoster, fetchPortraitFile, listDramaImages, generateDramaPortrait, getDramaSession, getDramaWorkspace } from '../lib/shortDramaApi';
import { useDramaWorkspace } from '../hooks/useDramaWorkspace';
import { IS_NATIVE_APP } from '../lib/runtime-config';
import { subscribeAppBack } from '../lib/appBackNavigation';
import { StoryboardConversation } from '../components/shortDrama/StoryboardConversation';
import { WorkbenchSidebar } from '../components/WorkbenchSidebar';
import { reduceStoryboardMessages } from '../lib/storyboardTimeline';
import './ShortDramaPage.css';

const VIDEO_QUALITY_LABELS = { preview: '预览视频', final: '最终视频' };
const VIDEO_STATUS_LABELS = { queued: '已提交', running: '处理中', succeeded: '已完成', failed: '失败' };
const SHOT_TONE_LABELS = { final: '最终已完成', preview: '预览已完成', running: '生成中', failed: '失败', empty: '未生成' };
const ROLE_SCOPE_LABELS = { global: '主角', major: '主要配角', minor: '次要配角', temp: '临时角色' };

function clock(totalSeconds) {
  const total = Math.max(0, Math.round(Number(totalSeconds) || 0));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

function succeededJob(jobs, shotId, quality) {
  const ready = jobs.filter((job) => job.shot_id === shotId && job.status === 'succeeded');
  return ready.find((job) => job.quality === quality) || ready[0] || null;
}

function chapterVideos(shots, jobs) {
  const shotsById = new Map(shots.map((shot, index) => [shot.id, { shot, index }]));
  return jobs
    .filter((job) => job.status === 'succeeded' && shotsById.has(job.shot_id))
    .map((job) => ({ job, ...shotsById.get(job.shot_id) }))
    .sort((a, b) => a.index - b.index || Number(a.job.quality === 'final') - Number(b.job.quality === 'final') || a.job.id.localeCompare(b.job.id));
}

function shotTone(jobs) {
  if (jobs.some((job) => job.status === 'failed')) return 'failed';
  if (jobs.some((job) => job.status === 'queued' || job.status === 'running')) return 'running';
  if (jobs.some((job) => job.status === 'succeeded' && job.quality === 'final')) return 'final';
  if (jobs.some((job) => job.status === 'succeeded')) return 'preview';
  return 'empty';
}

function PortraitPreview({ workId, portrait, alt }) {
  const [src, setSrc] = useState('');
  const [failed, setFailed] = useState(false);
  const remote = /^https?:\/\//.test(portrait.imagePath);
  useEffect(() => {
    if (!portrait.imagePath) { setSrc(''); setFailed(false); return undefined; }
    if (remote) { setSrc(portrait.imagePath); setFailed(false); return undefined; }
    let objectUrl = '';
    let cancelled = false;
    fetchPortraitFile(workId, portrait.id).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (!cancelled) { setSrc(objectUrl); setFailed(false); }
    }).catch(() => { if (!cancelled) { setFailed(true); setSrc(''); } });
    return () => { cancelled = true; if (objectUrl && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(objectUrl); };
  }, [workId, portrait.id, portrait.imagePath, remote]);
  if (!portrait.imagePath) return null;
  if (failed) return <p role='alert'>立绘文件不存在</p>;
  if (!src) return <p>立绘加载中</p>;
  return <img src={src} alt={alt} />;
}

function ShotFrame({ workId, chapterId, jobId }) {
  const [src, setSrc] = useState('');
  useEffect(() => {
    let objectUrl = '';
    let cancelled = false;
    fetchDramaPoster(workId, chapterId, jobId).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (cancelled) {
        URL.revokeObjectURL(objectUrl);
        return;
      }
      setSrc(objectUrl);
    });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [workId, chapterId, jobId]);
  if (!src) return null;
  return <img className='drama-thumb-frame' src={src} alt='' />;
}

function Drawer({ title, onClose, children, variant = 'drawer' }) {
  const ref = useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    (ref.current?.querySelector('[data-autofocus]') || ref.current)?.focus();
    function keydown(event) {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab') return;
      const controls = [...ref.current.querySelectorAll('button, input, textarea, select, a[href]')].filter((el) => !el.disabled);
      const first = controls[0]; const last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); previous?.focus(); };
  }, [onClose]);
  return <div className={`drama-overlay${variant === 'editor' ? ' drama-prompt-overlay' : ''}`} onClick={onClose}><section ref={ref} tabIndex={-1} role='dialog' aria-modal='true' aria-label={title} className={`drama-drawer${variant === 'editor' ? ' drama-prompt-dialog' : ''}`} onClick={(e) => e.stopPropagation()}><header><h2>{title}</h2><button type='button' className='drama-icon' aria-label={`关闭${title}`} onClick={onClose}><X size={18} /></button></header>{children}</section></div>;
}

export function ShortDramaPage({ appMode = IS_NATIVE_APP }) {
  const { workId, chapterId } = useParams();
  return <ChapterWorkbench key={`${workId}/${chapterId}`} appMode={appMode} workId={workId} chapterId={chapterId} />;
}

function ChapterWorkbench({ appMode, workId, chapterId }) {
  const navigate = useNavigate();
  const [chapter, setChapter] = useState(null);
  const [roles, setRoles] = useState([]);
  const workspace = useDramaWorkspace(workId, chapterId);
  const { draft, setDraft, sessions, sessionId, messages, saveError, saving, loading: sessionLoading } = workspace;
  const currentSession = sessions.find(session => session.id === sessionId);
  const sessionRunningElsewhere = currentSession?.running && currentSession.runningChapterId !== chapterId;
  const [videoJobs, setVideoJobs] = useState([]);
  const [imageJobs, setImageJobs] = useState([]);
  const [imageError, setImageError] = useState('');
  const [submittingImage, setSubmittingImage] = useState(false);
  const [imageParams, setImageParams] = useState({ width: 768, height: 1024, seed: 42 });
  const [monitorFrame, setMonitorFrame] = useState({ id: '', url: '' });
  const monitorFrameUrl = useRef('');
  const [videoError, setVideoError] = useState('');
  const [submittingVideo, setSubmittingVideo] = useState(false);
  const [deletingVideo, setDeletingVideo] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [drawer, setDrawer] = useState(null);
  const [mobileTab, setMobileTab] = useState('shots');
  const [sourceCollapsed, setSourceCollapsed] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const [sourceWidth, setSourceWidth] = useState(264);
  const [chatWidth, setChatWidth] = useState(348);
  const [viewId, setViewId] = useState(null);
  const [mobileScreen, setMobileScreen] = useState('shots');
  const [monitorQuality, setMonitorQuality] = useState('preview');
  const [portraitRoleId, setPortraitRoleId] = useState(null);
  const [editingPortraitId, setEditingPortraitId] = useState(null);
  const [stripOpen, setStripOpen] = useState(true);
  const [sizeText, setSizeText] = useState(null);
  const [panel, setPanel] = useState('shots');
  const [selectedId, setSelectedId] = useState(null);
  const [expandedShotId, setExpandedShotId] = useState(null);
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState('');
  const [inFlightMessage, setInFlightMessage] = useState('');
  const requestRef = useRef(null);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const closePromptEditor = useCallback(() => setExpandedShotId(null), []);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [{ nodes }, detail, jobs, images] = await Promise.all([fetchNodes(workId), workspace.initialize(), listDramaVideos(workId, chapterId), listDramaImages(workId)]);
      if (cancelled) return;
      const source = nodes.find(node => node.id === chapterId);
      if (!source || source.type !== 'chapter') throw new Error('该节点不是章节，无法打开短剧工作台');
      setChapter(source);
      setRoles(nodes.filter(node => node.type === 'character'));
      setVideoJobs(jobs);
      setImageJobs(images);
      if (detail.running && detail.runningChapterId === chapterId) followStream(detail.id);
    }
    load().catch(err => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; requestRef.current?.abort(); };
  }, [workId, chapterId, workspace.initialize]);

  useEffect(() => {
    if (!draft?.activeSessionId || sending) return;
    const timer = setInterval(() => {
      getDramaWorkspace(workId, chapterId).then(workspace.replaceBoard).then(workspace.refreshSessions).catch(err => setChatError(err.message));
    }, 2000);
    return () => clearInterval(timer);
  }, [draft?.activeSessionId, sending, workId, chapterId, workspace.replaceBoard, workspace.refreshSessions]);

  useEffect(() => {
    if (!sessionRunningElsewhere) return;
    const timer = setInterval(() => {
      workspace.refreshSessions().then(rows => {
        if (!rows.find(session => session.id === sessionId)?.running) {
          return getDramaSession(workId, chapterId, sessionId).then(detail => workspace.setMessages(detail.messages));
        }
      }).catch(err => setChatError(err.message));
    }, 2000);
    return () => clearInterval(timer);
  }, [sessionRunningElsewhere, sessionId, workId, chapterId, workspace.refreshSessions, workspace.setMessages]);

  useEffect(() => {
    if (!appMode) return undefined;
    let disposed = false;
    let unsubscribe;
    const handleBack = () => {
      if (drawer) {
        setDrawer(null);
        return;
      }
      if (expandedShotId) {
        setExpandedShotId(null);
        return;
      }
      if (mobileScreen === 'detail' || mobileTab !== 'shots' || panel !== 'shots') {
        setMobileTab('shots');
        setPanel('shots');
        setMobileScreen('shots');
        return;
      }
      navigate('/');
    };
    subscribeAppBack(handleBack).then((remove) => {
      if (disposed) remove();
      else unsubscribe = remove;
    });
    return () => {
      disposed = true;
      unsubscribe?.();
    };
  }, [appMode, drawer, expandedShotId, mobileScreen, mobileTab, panel, navigate]);

  useEffect(() => {
    if (!videoJobs.some(job => ['queued', 'running'].includes(job.status))) return;
    const timer = setInterval(() => {
      listDramaVideos(workId, chapterId).then(setVideoJobs).catch(err => setVideoError(err.message));
    }, 3000);
    return () => clearInterval(timer);
  }, [workId, chapterId, videoJobs]);
  useEffect(() => {
    if (!imageJobs.some(job => ['queued', 'running'].includes(job.status))) return;
    const timer = setInterval(async () => {
      try {
        const rows = await listDramaImages(workId);
        const completed = rows.some(job => job.status === 'succeeded' && imageJobs.some(previous => previous.id === job.id && ['queued', 'running'].includes(previous.status)));
        if (completed) {
          await workspace.flush();
          workspace.replacePortraits(await getDramaWorkspace(workId, chapterId));
        }
        setImageJobs(rows);
      } catch (err) { setImageError(err.message); }
    }, 3000);
    return () => clearInterval(timer);
  }, [imageJobs, workId, chapterId, workspace.flush, workspace.replacePortraits]);

  async function generatePortrait(portraitId) {
    setSubmittingImage(true); setImageError('');
    try {
      await workspace.flush();
      const job = await generateDramaPortrait(workId, portraitId, imageParams);
      setImageJobs(rows => [job, ...rows]);
    } catch (err) { setImageError(err.message); }
    finally { setSubmittingImage(false); }
  }

  const frameShotId = draft?.shots?.find((shot) => shot.id === selectedId)?.id || draft?.shots?.find((shot) => shot.id === viewId)?.id || draft?.shots?.[0]?.id || '';
  const frameJobId = (frameShotId && succeededJob(videoJobs, frameShotId, monitorQuality)?.id) || '';
  useEffect(() => {
    if (!frameJobId) {
      setMonitorFrame((current) => {
        if (!current.url) return current;
        URL.revokeObjectURL(current.url);
        monitorFrameUrl.current = '';
        return { id: '', url: '' };
      });
      return undefined;
    }
    let cancelled = false;
    fetchDramaVideo(workId, chapterId, frameJobId).then((blob) => {
      if (cancelled) return;
      const url = URL.createObjectURL(blob);
      if (monitorFrameUrl.current) URL.revokeObjectURL(monitorFrameUrl.current);
      monitorFrameUrl.current = url;
      setMonitorFrame({ id: frameJobId, url });
    }).catch((err) => { if (!cancelled) setVideoError(err.message); });
    return () => { cancelled = true; };
  }, [frameJobId, workId, chapterId]);
  useEffect(() => () => { if (monitorFrameUrl.current) URL.revokeObjectURL(monitorFrameUrl.current); }, []);

  async function switchSession(id, create = false) {
    try {
      await workspace.flush();
      requestRef.current?.abort(); requestRef.current = null;
      setSending(false); setInFlightMessage(''); setChatError('');
      const detail = create ? await workspace.newSession() : await workspace.loadSession(id);
      if (detail) setSelectedId(current => detail.workspace.shots.some(shot => shot.id === current) ? current : null);
      if (detail?.running && detail.runningChapterId === chapterId) followStream(detail.id);
    } catch (err) { setChatError(err.message); }
  }

  async function consume(controller, promise, activeId, sentDraft = '') {
    try {
      const result = await promise;
      if (controller.signal.aborted) return;
      setInFlightMessage('');
      workspace.replaceBoard(result.workspace);
      setSelectedId(current => result.workspace.shots.some(shot => shot.id === current) ? current : null);
      workspace.setMessages(result.messages);
      setDraft(current => ({ ...current, conversationDraft: '' }));
      workspace.refreshSessions().catch(err => setChatError(`会话列表刷新失败：${err.message}`));
    } catch (err) {
      if (!controller.signal.aborted) {
        setChatError(err.message);
        if (sentDraft) setDraft(current => ({ ...current, conversationDraft: current.conversationDraft || sentDraft }));
        try {
          const detail = await getDramaSession(workId, chapterId, activeId);
          if (!controller.signal.aborted) { workspace.replaceBoard(detail.workspace); workspace.setMessages(detail.messages); await workspace.refreshSessions(); }
        } catch (loadError) { setChatError(`${err.message}；历史读取失败：${loadError.message}`); }
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null; setSending(false); setInFlightMessage('');
      }
    }
  }
  function receiveEvent(controller) {
    return (event, data) => {
      if (controller.signal.aborted) return;
      if (event === 'message_updated' || event === 'storyboard_stream') {
        workspace.setMessages(rows => reduceStoryboardMessages(rows, event, data));
        if (event === 'message_updated' && data.role === 'user') setInFlightMessage('');
      }
      if (event === 'storyboard_updated' || event === 'portraits_updated') {
        workspace.replaceBoard(data.workspace);
        setSelectedId(current => data.workspace.shots.some(shot => shot.id === current) ? current : null);
      }
    };
  }
  function followStream(id) {
    const controller = new AbortController(); requestRef.current = controller; setSending(true);
    consume(controller, resumeStoryboardSession(workId, chapterId, id, controller.signal, receiveEvent(controller)), id);
  }

  async function generateVideos(ids, quality) {
    if (draft.shots.some((shot) => ids.includes(shot.id) && resolveInputMode(shot) === 'conflict')) {
      setVideoError('参考图和首帧来源只能提供一种');
      return;
    }
    setSubmittingVideo(true); setVideoError('');
    try {
      await workspace.flush();
      await generateDramaVideos(workId, chapterId, ids, quality);
      setVideoJobs(await listDramaVideos(workId, chapterId));
    } catch (err) { setVideoError(err.message); }
    finally { setSubmittingVideo(false); }
  }
  async function deleteVideo(job) {
    setDeletingVideo(true); setVideoError('');
    try {
      await deleteDramaVideo(workId, chapterId, job.id);
      setVideoJobs((jobs) => jobs.filter((item) => item.id !== job.id));
    } catch (err) { setVideoError(err.message); }
    finally { setDeletingVideo(false); }
  }
  async function sendMessage() {
    if (requestRef.current || !draft.conversationDraft.trim() || !sessionId) return;
    setChatError('');
    if (draft.sourceContent !== (chapter.content || '')) {
      setChatError('请先确认更新后的章节原文，再继续设计。'); return;
    }
    const text = draft.conversationDraft;
    const controller = new AbortController(); requestRef.current = controller;
    setSending(true); setInFlightMessage(text);
    setDraft(current => ({ ...current, conversationDraft: '' }));
    try {
      await workspace.flush();
      if (controller.signal.aborted) return;
      await consume(controller, sendStoryboardMessage(workId, chapterId, {
        message: text, source_content: draft.sourceContent, session_id: sessionId,
        selected_shot_id: draft.shots.some(shot => shot.id === selectedId) ? selectedId : null,
      }, controller.signal, receiveEvent(controller)), sessionId, text);
    } catch (err) {
      if (!controller.signal.aborted) { setChatError(err.message); setDraft(current => ({ ...current, conversationDraft: current.conversationDraft || text })); }
      if (requestRef.current === controller) { requestRef.current = null; setSending(false); setInFlightMessage(''); }
    }
  }

  function updateShot(id, patch) {
    setDraft((value) => ({ ...value, shots: value.shots.map((shot) => {
      if (shot.id !== id) return shot;
      const next = { ...shot, ...patch };
      const mode = resolveInputMode(next);
      return mode === 'conflict' ? next : { ...next, inputMode: mode };
    }) }));
  }
  function choose(id) {
    setViewId(id);
    setSelectedId(id);
    setMobileScreen('detail');
  }
  function addShot() {
    const shot = { ...createShot(), duration: 5 };
    setDraft((value) => ({ ...value, shots: [...value.shots, shot] }));
    choose(shot.id);
  }
  function moveShot(index, offset) {
    setDraft((value) => {
      const shots = [...value.shots];
      [shots[index], shots[index + offset]] = [shots[index + offset], shots[index]];
      return { ...value, shots };
    });
  }
  function removeShot(id) {
    const remaining = draft.shots.filter((shot) => shot.id !== id);
    setDraft({ ...draft, shots: remaining });
    if (selectedId === id) setSelectedId(null);
    if (viewId === id) setViewId(null);
  }
  function quote(text, label) {
    setDraft((value) => ({ ...value, conversationDraft: `${value.conversationDraft}${value.conversationDraft ? '\n\n' : ''}【${label}】\n${text}` }));
    setChatCollapsed(false);
    setMobileTab('chat');
  }
  async function copyShotPrompt(shot) {
    try {
      await navigator.clipboard.writeText(shot.prompt);
      setNotice('已复制本镜完整提示词。');
    } catch (err) {
      setNotice(`复制失败：${err.message}`);
    }
  }
  function exportDraft() {
    const data = { version: 1, work_id: workId, chapter_id: chapterId, chapter_title: chapter.title, ...draft, generation_requests: buildGenerationRequests(draft) };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `short-drama-${chapterId}.json`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setNotice('已导出分镜与生成参数；立绘仍需上传到生成环境后使用。');
  }
  function addPortrait(roleId) {
    const portrait = { id: crypto.randomUUID(), roleId, imagePath: '', prompt: '' };
    setDraft((value) => ({ ...value, portraits: [...value.portraits, portrait] }));
    setPortraitRoleId(roleId);
    setEditingPortraitId(portrait.id);
  }
  function changePortrait(id, patch) {
    setDraft((value) => ({ ...value, portraits: value.portraits.map((portrait) => portrait.id === id ? { ...portrait, ...patch } : portrait) }));
  }
  function removePortrait(id) {
    setDraft((value) => ({ ...value, portraits: value.portraits.filter((portrait) => portrait.id !== id), shots: value.shots.map((shot) => ({
      ...shot, roles: shot.roles.map((role) => role.portraitId === id ? { ...role, portraitId: null } : role),
    })) }));
  }

  const pageClass = `drama-page${appMode ? ' is-native' : ''}`;
  if (error) return <div className={`${pageClass} drama-load`}><Clapperboard size={28} /><p role='alert'>{error}</p><Link to='/'>返回小说</Link></div>;
  if (!draft || !chapter) return <div className={`${pageClass} drama-load`} role='status'>正在读取章节与短剧工作台…</div>;
  const paragraphs = (chapter.content || '').split('\n');
  const sourceChanged = draft.sourceContent !== (chapter.content || '');
  const totalDuration = draft.shots.reduce((total, shot) => total + Number(shot.duration), 0);
  const selectedIndex = draft.shots.findIndex((shot) => shot.id === selectedId);
  const selectedShot = selectedIndex >= 0 ? draft.shots[selectedIndex] : null;
  const viewed = draft.shots.find((shot) => shot.id === selectedId) || draft.shots.find((shot) => shot.id === viewId) || draft.shots[0] || null;
  const viewedIndex = viewed ? draft.shots.findIndex((shot) => shot.id === viewed.id) : -1;
  const activeRole = roles.find((role) => role.id === portraitRoleId) || roles[0] || null;
  const activePortraits = activeRole ? draft.portraits.filter((portrait) => portrait.roleId === activeRole.id) : [];
  const editingPortrait = activePortraits.find((portrait) => portrait.id === editingPortraitId) || activePortraits[0] || null;
  const editingPortraitIndex = editingPortrait ? activePortraits.findIndex((portrait) => portrait.id === editingPortrait.id) : -1;
  const mediaBusy = submittingImage || submittingVideo || [...imageJobs, ...videoJobs].some((job) => job.status === 'queued' || job.status === 'running');
  function reviseThisShot() {
    if (!viewed) return;
    setViewId(viewed.id);
    setSelectedId(viewed.id);
    setChatCollapsed(false);
    setMobileTab('chat');
    setMobileScreen('chat');
  }
  const expandedShotIndex = draft.shots.findIndex(shot => shot.id === expandedShotId);
  const expandedShot = draft.shots[expandedShotIndex];
  const widthText = sizeText ? sizeText.width : String(draft.width);
  const heightText = sizeText ? sizeText.height : String(draft.height);
  const widthValue = /^\d+$/.test(widthText) ? Number(widthText) : NaN;
  const heightValue = /^\d+$/.test(heightText) ? Number(heightText) : NaN;
  const sizeValid = [widthValue, heightValue].every(value => value >= 256 && value <= 1280 && value % 16 === 0);
  const editorLocked = sending || sessionLoading || Boolean(draft.activeSessionId);
  const editorStatus = editorLocked ? '生成期间只读' : saveError ? '保存失败' : saving ? '保存中…' : workspace.dirty ? '待自动保存' : '已自动保存';
  const viewedJobs = viewed ? videoJobs.filter((job) => job.shot_id === viewed.id) : [];
  const shownJob = viewedJobs.find((job) => job.quality === monitorQuality && job.status === 'succeeded') || viewedJobs.find((job) => job.status === 'succeeded') || viewedJobs.find((job) => job.quality === monitorQuality) || viewedJobs[0] || null;
  const playableJob = viewed ? succeededJob(videoJobs, viewed.id, monitorQuality) : null;
  const videos = chapterVideos(draft.shots, videoJobs);
  const viewedTiming = viewed ? videoTiming(Number(viewed.duration)) : null;
  function commitSize() {
    if (!sizeValid) return;
    setSizeText(null);
    setDraft(value => value.width === widthValue && value.height === heightValue ? value : { ...value, width: widthValue, height: heightValue });
  }

  return <div className={pageClass} data-screen={mobileTab === 'shots' ? (panel === 'portraits' ? 'ports' : mobileScreen) : mobileTab}>
    <header className='drama-top'>
      <Link to='/' className='drama-back' aria-label='返回小说'><ArrowLeft size={18} /></Link>
      <div className='drama-crumb'><small>短剧 /</small><h1>{chapter.title}</h1></div>
      <div className='drama-sub'>
        <output className='drama-chapter-duration' aria-label='全章分镜总时长' aria-live='polite'>共 {draft.shots.length} 镜 · 总时长 {formatDramaDuration(totalDuration)}</output>
        <span className={`drama-save ${saveError ? 'is-error' : ''}`} aria-live='polite'>{saveError ? '未保存' : saving ? '保存中…' : workspace.dirty ? '待保存' : <><Check size={13} /> 已保存</>}</span>
      </div>
      <div className='drama-seg' role='tablist' aria-label='主设计区'>
        <button type='button' role='tab' aria-selected={panel === 'shots'} aria-label={`分镜设计 ${draft.shots.length}`} onClick={() => { setPanel('shots'); setMobileTab('shots'); setMobileScreen('shots'); }}>分镜 <b>{draft.shots.length}</b></button>
        <button type='button' role='tab' aria-selected={panel === 'portraits'} aria-label={`立绘设计 ${draft.portraits.length}`} onClick={() => { setPanel('portraits'); setMobileTab('shots'); setMobileScreen('shots'); }}>立绘 <b>{draft.portraits.length}</b></button>
      </div>
      <span className='drama-sp' />
      <button type='button' disabled={editorLocked} onClick={() => setDrawer('settings')} aria-label='本章生成设置'><Settings2 size={15} />本章设置<span className='drama-dim'>{draft.width}×{draft.height}</span></button>
      <button type='button' onClick={exportDraft} disabled={!draft.shots.length}><Download size={15} />导出</button>
    </header>
    {draft.activeSessionId && !sending && <div className='drama-notice'>本章分镜正在后台生成。<button type='button' disabled={sessionLoading} onClick={() => switchSession(draft.activeSessionId)}>查看生成会话</button></div>}
    {sessionRunningElsewhere && <div className='drama-notice'>当前会话正在为其他章节生成分镜。<Link to={`/short-drama/${workId}/${currentSession.runningChapterId}`}>查看生成章节</Link></div>}
    {sourceChanged && <div className='drama-warning'>章节原文已更新，现有分镜仍基于旧版正文。<button type='button' disabled={sending || sessionLoading || Boolean(draft.activeSessionId)} onClick={() => setDraft({ ...draft, sourceContent: chapter.content || '' })}>确认以当前原文继续设计</button></div>}
    {saveError && <div className='drama-warning' role='alert'>{saveError}<button type='button' onClick={() => workspace.flush().catch(() => {})}>重新保存</button></div>}
    {notice && <div className='drama-notice' role='status'>{notice}<button type='button' aria-label='关闭提示' onClick={() => setNotice('')}><X size={14} /></button></div>}
    <nav className='drama-mobile-tabs' aria-label='工作台面板'>
      <button type='button' aria-pressed={mobileTab === 'shots' && panel === 'shots' && mobileScreen !== 'detail'} onClick={() => { setMobileTab('shots'); setPanel('shots'); setMobileScreen('shots'); }}>分镜</button>
      <button type='button' aria-pressed={mobileTab === 'shots' && panel === 'portraits'} onClick={() => { setMobileTab('shots'); setPanel('portraits'); setMobileScreen('shots'); }}>立绘</button>
      <button type='button' aria-label='章节原文' aria-pressed={mobileTab === 'source'} onClick={() => { setMobileTab('source'); setMobileScreen('source'); }}>原文</button>
      <button type='button' aria-label='设计助手' aria-pressed={mobileTab === 'chat'} onClick={() => { setMobileTab('chat'); setChatCollapsed(false); setMobileScreen('chat'); }}>助手</button>
    </nav>
    <div className='drama-workspace'>
      <WorkbenchSidebar side='left' title='章节原文' icon={<BookOpen size={16} />} collapsed={sourceCollapsed} onCollapsedChange={setSourceCollapsed} width={sourceWidth} onWidthChange={setSourceWidth} headerExtra={<span>{(chapter.content || '').length.toLocaleString()} 字</span>} className={`drama-source${mobileTab === 'source' ? '' : ' drama-mobile-inactive'}`}>
        <div className='drama-source-body pretty-scrollbar'>{paragraphs.length ? paragraphs.map((paragraph, index) => <article key={index} data-paragraph={index} data-line={index + 1} className={paragraph.trim() ? '' : 'is-empty'}><div className='drama-paragraph-number'>{String(index + 1).padStart(2, '0')}</div><p>{paragraph || '\u00a0'}</p>{paragraph.trim() && <div className='drama-paragraph-actions'><button type='button' aria-label={`引用原文第 ${index + 1} 行`} onClick={() => quote(paragraph, `原文第 ${index + 1} 行`)}><Quote size={12} />引用到对话</button></div>}</article>) : <p className='drama-muted'>本章节暂无正文，请先返回小说填写。</p>}</div>
      </WorkbenchSidebar>
      <section className={`drama-shots drama-panel${mobileTab === 'shots' ? '' : ' drama-mobile-inactive'}`} aria-label='分镜工作区'>
        {panel === 'portraits' ? <div className='drama-ports pretty-scrollbar'>
          <div className='drama-role-list'>
            <h5>小说角色 · {roles.length}</h5>
            {!roles.length && <p>当前作品暂无角色，请先在小说中创建角色节点。</p>}
            {roles.map((role) => {
              const count = draft.portraits.filter((portrait) => portrait.roleId === role.id).length;
              return <button type='button' key={role.id} className={activeRole?.id === role.id ? 'is-on' : ''} onClick={() => { setPortraitRoleId(role.id); setEditingPortraitId(null); }}><span className='drama-avatar' aria-hidden='true'>{role.title.slice(0, 1)}</span><span><b>{role.title}</b><small>{count ? `${count} 张立绘` : '暂无立绘'}</small></span></button>;
            })}
          </div>
          {activeRole && <div className='drama-port-main'>
            <header>
              <h2>{activeRole.title}</h2>
              {ROLE_SCOPE_LABELS[activeRole.scope] && <span className='drama-scope'>{ROLE_SCOPE_LABELS[activeRole.scope]}</span>}
              <span className='drama-sp' />
              <details className='drama-image-settings'><summary>图片设置 <span>{imageParams.width}×{imageParams.height}</span><ChevronDown size={13} /></summary><div className='drama-size-settings'>
                {[['width', '图片宽度', 256, 2048, 16], ['height', '图片高度', 256, 2048, 16]].map(([field, label, min, max, step]) => <label className='drama-field' key={field}><span>{label}</span><input aria-label={label} type='number' min={min} max={max} step={step} value={imageParams[field]} onChange={e => setImageParams(params => ({ ...params, [field]: Number(e.target.value) }))} /></label>)}
              </div><details className='drama-advanced'><summary>高级参数</summary><label className='drama-field'><span>随机种子</span><input aria-label='图片种子' type='number' min='0' max='4294967295' step='1' value={imageParams.seed} onChange={e => setImageParams(params => ({ ...params, seed: Number(e.target.value) }))} /></label></details></details>
            </header>
            {imageError && <p role='alert'>{imageError}</p>}
            {activeRole.content && <blockquote className='drama-setting'>小说设定：{activeRole.content}</blockquote>}
            <div className='drama-gallery'>
              {activePortraits.map((portrait, portraitIndex) => {
                const imageJob = imageJobs.find(job => job.portrait_id === portrait.id);
                const selected = portrait.id === editingPortrait?.id;
                return <button type='button' className={`drama-gallery-card${selected ? ' is-on' : ''}`} key={portrait.id} onClick={() => setEditingPortraitId(portrait.id)}>
                  {portrait.imagePath ? <PortraitPreview workId={workId} portrait={portrait} alt={selected ? `${activeRole.title}立绘` : ''} /> : null}
                  {!portrait.imagePath && <span className='drama-gallery-state'>{imageJob?.status === 'running' || imageJob?.status === 'queued' ? '绘制中' : ''}</span>}
                  <span className='drama-gallery-tag'>立绘 {portraitIndex + 1}</span>
                </button>;
              })}
              <button type='button' className='drama-gallery-add' aria-label={`为${activeRole.title}添加立绘`} disabled={editorLocked} onClick={() => addPortrait(activeRole.id)}><Plus size={18} />添加立绘</button>
            </div>
            {editingPortrait && <div className='drama-card drama-portrait-editor'>
              <div className='drama-card-h'>立绘 {editingPortraitIndex + 1} · 提示词</div>
              <textarea aria-label={`${activeRole.title}立绘 ${editingPortraitIndex + 1} 提示词`} value={editingPortrait.prompt} disabled={editorLocked || ['queued', 'running'].includes(imageJobs.find(job => job.portrait_id === editingPortrait.id)?.status)} onChange={(e) => changePortrait(editingPortrait.id, { prompt: e.target.value })} />
              <div className='drama-portrait-actions'>
                <span>{draft.shots.some(shot => shot.roles.some(role => role.portraitId === editingPortrait.id)) ? <>已用于镜头 <b>{draft.shots.flatMap((shot, shotIndex) => shot.roles.some(role => role.portraitId === editingPortrait.id) ? [String(shotIndex + 1).padStart(2, '0')] : []).join(' · ')}</b></> : '尚未用于镜头'}</span>
                <button type='button' disabled={editorLocked || ['queued', 'running'].includes(imageJobs.find(job => job.portrait_id === editingPortrait.id)?.status)} onClick={() => removePortrait(editingPortrait.id)}><Trash2 size={14} />删除这张</button>
                <button type='button' className='drama-primary' aria-label={`生成${activeRole.title}立绘 ${editingPortraitIndex + 1}`} disabled={editorLocked || mediaBusy || !editingPortrait.prompt.trim()} onClick={() => generatePortrait(editingPortrait.id)}><Sparkles size={15} />{editingPortrait.imagePath ? '重新生成立绘' : '生成立绘'}</button>
              </div>
              {imageJobs.find(job => job.portrait_id === editingPortrait.id) && <p role={imageJobs.find(job => job.portrait_id === editingPortrait.id).status === 'failed' ? 'alert' : 'status'}>{imageJobs.find(job => job.portrait_id === editingPortrait.id).status === 'failed' ? imageJobs.find(job => job.portrait_id === editingPortrait.id).error : ({ queued: '已提交，等待生成', running: '处理中', succeeded: '立绘已生成' })[imageJobs.find(job => job.portrait_id === editingPortrait.id).status]}</p>}
              {mediaBusy && !['queued', 'running'].includes(imageJobs.find(job => job.portrait_id === editingPortrait.id)?.status) && <p role='status'>已有生图或生视频正在处理</p>}
            </div>}
          </div>}
        </div> : <div className='drama-shot-pane'>
          {!draft.shots.length && <div className='drama-empty'><div className='drama-empty-icon'><Clapperboard size={30} /></div><h3>还没有分镜</h3><p>添加第一个镜头，编写完整的视频提示词。<br />也可以先在右侧整理给分镜设计助手的要求。</p><button type='button' disabled={editorLocked} onClick={addShot}><Plus size={15} />添加分镜</button></div>}
          {viewed && <fieldset className='drama-shot-list pretty-scrollbar drama-editor-fields' disabled={sending || sessionLoading || Boolean(draft.activeSessionId)}>
            <article className={`drama-shot${selectedId === viewed.id ? ' is-selected' : ''}`}>
              <button type='button' className='drama-mobile-back' onClick={() => setMobileScreen('shots')}><ArrowLeft size={16} />全部镜头</button>
              <div className='drama-stage'>
                <div className='drama-col'>
                  <section className='drama-monitor' aria-label={`镜头 ${viewedIndex + 1} 画面`}>
                    <div className='drama-frame'>
                      {playableJob && monitorFrame.id === playableJob.id ? <video className='drama-monitor-video' src={monitorFrame.url} controls playsInline preload='auto' onLoadedData={(event) => { const node = event.currentTarget; if (node.currentTime === 0) node.currentTime = 0.001; }} /> : <span className='drama-frame-hint'>{playableJob ? '画面加载中' : '生成后在这里播放'}</span>}
                      <span className='drama-tc'>{`00:00 / ${clock(viewed.duration)}`}</span>
                    </div>
                    <div className='drama-monitor-bar'>
                      <span className='drama-qseg'>
                        {['preview', 'final'].map((quality) => <button type='button' key={quality} className={viewedJobs.some((job) => job.quality === quality && job.status === 'succeeded') ? 'has' : ''} aria-pressed={shownJob?.quality === quality} disabled={!viewedJobs.some((job) => job.quality === quality && job.status === 'succeeded')} onClick={() => setMonitorQuality(quality)}><i />{quality === 'preview' ? '预览' : '最终'}</button>)}
                      </span>
                      <span className='drama-monitor-info'>{shownJob ? VIDEO_STATUS_LABELS[shownJob.status] : '尚无成片'}</span>
                      {viewedJobs.map((job) => <span key={job.id} className='drama-sr-only'>{VIDEO_QUALITY_LABELS[job.quality]}</span>)}
                      <button type='button' className='drama-icon' aria-label='全屏播放' onClick={() => document.querySelector('.drama-monitor-video')?.requestFullscreen?.()}><Maximize2 size={15} /></button>
                      {playableJob && <button type='button' className='drama-monitor-delete' disabled={deletingVideo} onClick={() => deleteVideo(playableJob)}>删除{VIDEO_QUALITY_LABELS[playableJob.quality]}</button>}
                    </div>
                  </section>
                  <div className='drama-card'>
                    <div className='drama-card-h'><Users size={14} />出场角色</div>
                    <div className='drama-role-line'>{viewed.roles.some(item => roles.some(role => role.id === item.roleId)) ? viewed.roles.map(item => { const role = roles.find(role => role.id === item.roleId); if (!role) return null; const portraitIndex = draft.portraits.filter((portrait) => portrait.roleId === role.id && portrait.imagePath).findIndex((portrait) => portrait.id === item.portraitId); return <span className='drama-role-pill' key={item.roleId}><span className='drama-role-tag'><span className='drama-avatar' aria-hidden='true'>{role.title.slice(0, 1)}</span>{role.title}</span>{portraitIndex >= 0 && <small>{`立绘 ${portraitIndex + 1}`}</small>}</span>; }) : <span className='drama-role-empty'>未关联角色</span>}</div>
                    {roles.length > 0 && <details className='drama-role-editor'><summary>编辑出场角色</summary>{roles.map((role) => {
                      const selected = viewed.roles.find(item => item.roleId === role.id);
                      const choices = draft.portraits.filter(portrait => portrait.roleId === role.id && portrait.imagePath);
                      return <div key={role.id}><label><input type='checkbox' aria-label={`镜头 ${viewedIndex + 1} 关联角色 ${role.title}`} checked={Boolean(selected)} onChange={(e) => updateShot(viewed.id, { roles: e.target.checked ? [...viewed.roles, { roleId: role.id, portraitId: null }] : viewed.roles.filter(item => item.roleId !== role.id) })} />{role.title}</label>{selected && <div className='drama-portrait-choices' role='radiogroup' aria-label={`镜头 ${viewedIndex + 1} ${role.title} 立绘`}><label><input type='radio' name={`shot-${viewed.id}-${role.id}`} aria-label={`镜头 ${viewedIndex + 1} ${role.title} 无`} checked={selected.portraitId == null} onChange={() => updateShot(viewed.id, { roles: viewed.roles.map(item => item.roleId === role.id ? { ...item, portraitId: null } : item) })} />无</label>{choices.map((portrait, portraitIndex) => <label key={portrait.id}><input type='radio' name={`shot-${viewed.id}-${role.id}`} aria-label={`镜头 ${viewedIndex + 1} ${role.title} 的第 ${portraitIndex + 1} 张立绘`} checked={selected.portraitId === portrait.id} onChange={() => updateShot(viewed.id, { roles: viewed.roles.map(item => item.roleId === role.id ? { ...item, portraitId: portrait.id } : item) })} /><PortraitPreview workId={workId} portrait={portrait} alt={`${role.title}立绘`} /></label>)}</div>}</div>;
                    })}</details>}
                  </div>
                  <div className='drama-card drama-params'>
                    <label>时长<span className='drama-stepper'><button type='button' aria-label={`减少镜头 ${viewedIndex + 1} 时长`} onClick={() => updateShot(viewed.id, { duration: Math.max(1, Math.round(Number(viewed.duration) || 0) - 1) })}>−</button><span className='drama-stepper-val'><input type='number' min='1' max='15' step='any' aria-label={`镜头 ${viewedIndex + 1} 时长`} value={viewed.duration} onChange={(e) => updateShot(viewed.id, { duration: e.target.value === '' ? '' : Number(e.target.value) })} /><span>秒</span></span><button type='button' aria-label={`增加镜头 ${viewedIndex + 1} 时长`} onClick={() => updateShot(viewed.id, { duration: Math.min(15, Math.round(Number(viewed.duration) || 0) + 1) })}>+</button></span>{viewedTiming && <small>{viewedTiming.frames} 帧 · 实际 {viewedTiming.actualDuration.toFixed(2)} 秒</small>}</label>
                    <label className='drama-source-field'>首帧来源<select className='drama-source-select' aria-label={`镜头 ${viewedIndex + 1} 首帧来源`} value={viewed.firstFrameShotId || ''} onChange={(e) => updateShot(viewed.id, { firstFrameShotId: e.target.value })}><option value=''>不锁定</option>{draft.shots.map((other, otherIndex) => otherIndex < viewedIndex ? <option key={other.id} value={other.id}>{`${String(otherIndex + 1).padStart(2, '0')} ${other.title}`}</option> : null)}</select></label>
                    {resolveInputMode(viewed) === 'conflict' && <p className='drama-size-error' role='alert'>参考图和首帧来源只能提供一种</p>}
                    <details className='drama-advanced'><summary><span>高级设置</span><ChevronDown size={13} /><span className='drama-adv-sum'>{viewed.mode === 'turbo' ? 'Turbo · 8 步' : '基础 · 20 步'} · 种子 {viewed.seed}</span><span className='drama-sr-only'>项</span></summary>{viewedTiming && <p className='drama-shot-timing'>{viewedTiming.frames} 帧 · 24fps · 预计 {viewedTiming.actualDuration.toFixed(2)} 秒</p>}<div className='drama-option-grid'><label className='drama-field'><span>采样模式</span><select aria-label={`镜头 ${viewedIndex + 1} 采样模式`} value={viewed.mode} onChange={(e) => updateShot(viewed.id, { mode: e.target.value })}><option value='turbo'>Turbo · 8 步</option><option value='base'>基础 · 20 步</option></select></label><label className='drama-field'><span>随机种子</span><input type='number' min='0' step='1' value={viewed.seed} onChange={(e) => updateShot(viewed.id, { seed: e.target.value })} aria-label={`镜头 ${viewedIndex + 1} 随机种子`} /></label></div></details>
                  </div>
                  <div className='drama-gen' role='group' aria-label={`镜头 ${viewedIndex + 1} 操作区`}>
                    {videoError && <p role='alert'>{videoError}</p>}
                    {mediaBusy && <p role='status'>已有生图或生视频正在处理</p>}
                    {['preview', 'final'].map(quality => <button key={quality} type='button' className={quality === 'final' ? 'drama-primary' : ''} disabled={!sizeValid || !viewed.prompt.trim() || resolveInputMode(viewed) === 'conflict' || mediaBusy} onClick={() => generateVideos([viewed.id], quality)}><Sparkles size={14} />生成{VIDEO_QUALITY_LABELS[quality]}</button>)}
                  </div>
                </div>
                <div className='drama-col'>
                  <div className='drama-editor'>
                    <div className='drama-editor-h'>
                      <span className='drama-shot-number'>{String(viewedIndex + 1).padStart(2, '0')}</span>
                      <input aria-label={`镜头 ${viewedIndex + 1} 名称`} placeholder='为这个镜头起个名字' value={viewed.title} onChange={(e) => updateShot(viewed.id, { title: e.target.value })} />
                      <button type='button' className='drama-icon' aria-label='上一个镜头' disabled={viewedIndex <= 0} onClick={() => choose(draft.shots[viewedIndex - 1].id)}><ChevronLeft size={16} /></button>
                      <button type='button' className='drama-icon' aria-label='下一个镜头' disabled={viewedIndex >= draft.shots.length - 1} onClick={() => choose(draft.shots[viewedIndex + 1].id)}><ChevronRight size={16} /></button>
                      <details className='drama-more'><summary><MoreHorizontal size={16} /><span className='drama-sr-only'>更多</span><span className='drama-sr-only'>菜单</span></summary>
                        <div className='drama-more-menu'>
                          <button type='button' disabled={!viewed.prompt} onClick={(event) => { copyShotPrompt(viewed); event.currentTarget.closest('details').open = false; }}>复制提示词</button>
                          <button type='button' aria-label={`上移镜头 ${viewedIndex + 1}`} disabled={viewedIndex === 0} onClick={(event) => { moveShot(viewedIndex, -1); event.currentTarget.closest('details').open = false; }}><ArrowUp size={14} />上移</button>
                          <button type='button' aria-label={`下移镜头 ${viewedIndex + 1}`} disabled={viewedIndex === draft.shots.length - 1} onClick={(event) => { moveShot(viewedIndex, 1); event.currentTarget.closest('details').open = false; }}><ArrowDown size={14} />下移</button>
                          <button type='button' aria-label='添加分镜' disabled={editorLocked} onClick={(event) => { event.currentTarget.closest('details').open = false; addShot(); }}><Plus size={14} />添加分镜</button>
                          <button type='button' aria-label={`删除镜头 ${viewedIndex + 1}`} onClick={(event) => { event.currentTarget.closest('details').open = false; removeShot(viewed.id); }}><Trash2 size={14} />删除</button>
                        </div>
                      </details>
                    </div>
                    <div className='drama-prompt-heading'><label htmlFor={`drama-prompt-${viewed.id}`}>视频提示词</label><small>{viewed.prompt.length} 字</small><button type='button' className='drama-expand' aria-label={`展开编辑镜头 ${viewedIndex + 1} 提示词`} onClick={() => setExpandedShotId(viewed.id)}>展开全文</button></div>
                    <textarea className='drama-shot-prompt' rows={12} id={`drama-prompt-${viewed.id}`} aria-label={`镜头 ${viewedIndex + 1} 提示词`} placeholder='描述人物、环境、动作、景别、运镜和声音。需要对白时，把具体台词写入提示词。' value={viewed.prompt} onChange={(e) => updateShot(viewed.id, { prompt: e.target.value })} />
                    <footer className='drama-editor-f'><Check size={13} /><span>{editorStatus}</span><button type='button' disabled={!viewed.prompt} onClick={() => copyShotPrompt(viewed)}>复制</button><button type='button' className='drama-soft' onClick={reviseThisShot}><Sparkles size={13} />让助手改这一镜</button></footer>
                  </div>
                </div>
              </div>
            </article>
          </fieldset>}
          {draft.shots.length > 0 && <div className='drama-shot-index' aria-label='全部镜头'>{draft.shots.map((shot, index) => { const jobs = videoJobs.filter(job => job.shot_id === shot.id); const tone = shotTone(jobs); const cover = jobs.find(job => job.status === 'succeeded' && job.quality === 'final') || jobs.find(job => job.status === 'succeeded'); const cast = shot.roles.filter(item => roles.some(role => role.id === item.roleId)); return <button type='button' className={`drama-tile${selectedId === shot.id ? ' is-on' : ''}`} key={shot.id} aria-pressed={selectedId === shot.id} aria-label={`选择镜头 ${index + 1}`} onClick={() => choose(shot.id)}>
              <span className={`drama-thumb is-${tone}`}>{cover && <ShotFrame workId={workId} chapterId={chapterId} jobId={cover.id} />}<span className='drama-tile-no'>{String(index + 1).padStart(2, '0')}</span><span className='drama-tile-du'>{Number(shot.duration) || 0}s</span></span>
              <span className='drama-tile-copy'><span className='drama-tile-title'>{shot.title || '未命名'}</span><span className='drama-tile-more'>{shot.prompt}</span><span className='drama-tile-foot'>{cast.slice(0, 3).map(item => <span key={item.roleId} className='drama-avatar' aria-hidden='true'>{roles.find(role => role.id === item.roleId).title.slice(0, 1)}</span>)}<span className={`drama-mini is-${tone}`}>{SHOT_TONE_LABELS[tone]}</span></span></span>
            </button>; })}<button type='button' className='drama-tile drama-tile-add' aria-label='添加分镜' disabled={editorLocked} onClick={addShot}><span className='drama-thumb'><Plus size={16} /></span><span className='drama-tile-title'>添加镜头</span></button></div>}
          {videos.length > 0 && <div className={`drama-filmstrip${stripOpen ? '' : ' is-collapsed'}`} aria-label='本章视频'>
            <div className='drama-rhy'>
              <span>成片<b aria-label='成片总时长'>{clock(videos.reduce((total, item) => total + (Number(item.job.duration) || 0), 0))}</b></span>
              <div className='drama-rhy-bar'>{videos.map(({ job, shot, index }) => { const tone = shotTone([job]); return <button type='button' key={job.id} className={`is-${tone}${playableJob?.id === job.id ? ' is-on' : ''}`} style={{ flexGrow: Math.max(Number(job.duration) || 0, 1) }} aria-label={`跳到镜头 ${index + 1} 的${VIDEO_QUALITY_LABELS[job.quality]}`} onClick={() => { setMonitorQuality(job.quality); choose(shot.id); }}>{String(index + 1).padStart(2, '0')}</button>; })}</div>
              <button type='button' className='drama-strip-toggle' aria-expanded={stripOpen} aria-label={stripOpen ? '收起本章视频' : '展开本章视频'} onClick={() => setStripOpen(open => !open)}>{stripOpen ? <ChevronUp size={15} /> : <ChevronDown size={15} />}{stripOpen ? '收起' : '展开'}</button>
            </div>
            <div className='drama-tiles' hidden={!stripOpen}>{videos.map(({ job, shot, index }) => { const tone = shotTone([job]); const label = `播放镜头 ${index + 1} 的${VIDEO_QUALITY_LABELS[job.quality]}`; return <button type='button' className={`drama-tile${playableJob?.id === job.id ? ' is-on' : ''}`} key={job.id} aria-pressed={playableJob?.id === job.id} aria-label={label} onClick={() => { setMonitorQuality(job.quality); choose(shot.id); }}>
              <span className={`drama-thumb is-${tone}`}><ShotFrame workId={workId} chapterId={chapterId} jobId={job.id} /><span className='drama-tile-no'>{String(index + 1).padStart(2, '0')}</span><span className='drama-tile-du'>{Number(job.duration) || 0}s</span></span>
              <span className='drama-tile-copy'><span className='drama-tile-title'>{shot.title || '未命名'}</span><span className='drama-tile-more'>{VIDEO_QUALITY_LABELS[job.quality]}</span><span className='drama-tile-foot'><span className={`drama-mini is-${tone}`}>{SHOT_TONE_LABELS[tone]}</span></span></span>
            </button>; })}</div><div className='drama-tiles-fade' aria-hidden='true' hidden={!stripOpen} />
          </div>}
        </div>}
      </section>
      <WorkbenchSidebar side='right' title='分镜设计助手' icon={<Sparkles size={16} />} collapsed={chatCollapsed} onCollapsedChange={setChatCollapsed} width={chatWidth} onWidthChange={setChatWidth} headerExtra={<div className='drama-session-controls'><select aria-label='分镜会话' value={sessionId || ''} disabled={sessionLoading} onChange={event => switchSession(event.target.value)}>{sessions.map(session => <option key={session.id} value={session.id}>{session.title}{session.running ? ' · 生成中' : ''}</option>)}</select><button type='button' aria-label='新建会话' title='新建会话' disabled={sessionLoading} onClick={() => switchSession(null, true)}><Plus size={14} /></button></div>} className={`drama-chat${mobileTab === 'chat' ? '' : ' drama-mobile-inactive'}`}>
        <StoryboardConversation
          messages={messages}
          sending={sending}
          inFlightMessage={inFlightMessage}
          chatError={chatError}
        />
        <form className='drama-composer' onSubmit={(event) => { event.preventDefault(); sendMessage(); }}><label className='drama-sr-only' htmlFor='drama-chat-input'>对话输入</label>{selectedShot && <div className='drama-linked-shot'><Link2 size={13} /><span>{`关联镜头 ${String(selectedIndex + 1).padStart(2, '0')}：${selectedShot.title}`}</span><button type='button' aria-label='取消关联镜头' onClick={() => setSelectedId(null)}><X size={13} /></button></div>}<div className='drama-composer-row'><textarea id='drama-chat-input' placeholder={selectedShot ? '告诉助手怎么改这个镜头…' : '让助手设计或修改分镜…'} value={draft.conversationDraft} onChange={(e) => setDraft({ ...draft, conversationDraft: e.target.value })} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} /><button type='submit' className='drama-composer-send' aria-label='发送给 Agent' disabled={sending || sessionLoading || Boolean(draft.activeSessionId) || sessionRunningElsewhere || !draft.conversationDraft.trim()}><Send size={16} /></button></div></form>
      </WorkbenchSidebar>
    </div>
    {expandedShot && <Drawer variant='editor' title={`镜头 ${expandedShotIndex + 1} · 视频提示词`} onClose={closePromptEditor}>
      <div className='drama-prompt-editor-body'>
        <p className='drama-muted'>{expandedShot.title || '未命名镜头'}</p>
        <textarea className='drama-expanded-prompt' aria-label='完整视频提示词' data-autofocus readOnly={editorLocked} value={expandedShot.prompt} onChange={event => updateShot(expandedShot.id, { prompt: event.target.value })} />
        {saveError && <p role='alert'>{saveError}</p>}
      </div>
      <footer className='drama-prompt-editor-footer'><span role='status'>{editorLocked ? '生成期间只读' : saveError ? '保存失败' : saving ? '保存中…' : workspace.dirty ? '待自动保存' : '已保存'}</span><button type='button' className='drama-primary' onClick={closePromptEditor}>完成</button></footer>
    </Drawer>}
    {drawer === 'settings' && <Drawer title='本章生成设置' onClose={closeDrawer}>
      <div className='drama-drawer-content'><h3 className='drama-settings-heading'>视频画幅</h3><div className='drama-frame-controls'><label>宽<input aria-label='画面宽度' inputMode='numeric' value={widthText} disabled={editorLocked} onChange={(e) => setSizeText({ width: e.target.value, height: heightText })} onBlur={commitSize} /></label><label>高<input aria-label='画面高度' inputMode='numeric' value={heightText} disabled={editorLocked} onChange={(e) => setSizeText({ width: widthText, height: e.target.value })} onBlur={commitSize} /></label><span>24fps</span>{[[960, 544], [544, 960], [1280, 720], [720, 1280]].map(([width, height]) => <button type='button' key={`${width}x${height}`} disabled={editorLocked} aria-pressed={widthText === String(width) && heightText === String(height)} onClick={() => { setSizeText(null); setDraft(value => ({ ...value, width, height })); }}>{width}×{height}</button>)}</div>{!sizeValid && <p className='drama-size-error' role='alert'>宽和高须为 256 到 1280 之间的 16 倍数</p>}<p className='drama-muted'>最终视频使用此画幅，预览视频等比降低分辨率。</p><label className='drama-field'><span>统一视觉风格</span><textarea value={draft.style} onChange={(e) => setDraft({ ...draft, style: e.target.value })} placeholder='例如：电影写实风格，自然光，克制的镜头运动。' /></label></div>
    </Drawer>}
  </div>;
}
