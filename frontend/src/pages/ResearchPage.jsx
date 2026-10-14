import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, BookOpen, Bot, Download, FileText, LoaderCircle, MessageSquarePlus, Plus, Send, Upload, UserRound, X } from "lucide-react";
import { researchApi } from "../lib/researchApi";
import { authFetch } from "../lib/authFetch";
import { remarkHtmlBreaks } from "../lib/markdown";

function Message({ message }) {
  const mine = message.role === "user";
  return (
    <div className={`flex items-start gap-3 ${mine ? "justify-end" : ""}`}>
      {!mine && <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-600"><Bot className="h-4 w-4" /></div>}
      <div className={`max-w-[78%] ${mine ? "rounded-2xl rounded-tr-md bg-indigo-600 text-white" : "rounded-2xl rounded-tl-md border border-slate-200 bg-white text-slate-700"} px-4 py-3 shadow-sm`}>
        {message.referenced_works?.map((work) => (
          <div key={work.id} className={`mb-2 flex items-center gap-1.5 text-xs ${mine ? "text-indigo-100" : "text-indigo-500"}`}>
            <BookOpen className="h-3.5 w-3.5" />引用《{work.filename}》
          </div>
        ))}
        {message.chapter_reference && <div className={`mb-2 flex items-center gap-1.5 text-xs ${mine ? "text-indigo-100" : "text-indigo-500"}`}>
          <FileText className="h-3.5 w-3.5" />引用章节：{message.chapter_reference.heading}
        </div>}
        <div className="prose prose-slate max-w-none text-sm leading-6 text-inherit">
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkHtmlBreaks]}>{message.content}</ReactMarkdown>
        </div>
      </div>
      {mine && <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600"><UserRound className="h-4 w-4" /></div>}
    </div>
  );
}

export function ResearchPage() {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [works, setWorks] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [selectedWorkId, setSelectedWorkId] = useState(null);
  const [libraryWorks, setLibraryWorks] = useState([]);
  const [versions, setVersions] = useState([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState(null);
  const [panelTab, setPanelTab] = useState("artifacts");
  const [chapterVersionId, setChapterVersionId] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [selectedChapterIndex, setSelectedChapterIndex] = useState(null);
  const [chapterDetail, setChapterDetail] = useState(null);
  const [chapterReference, setChapterReference] = useState(null);
  const [sessionId, setSessionId] = useState("");
  const [session, setSession] = useState(null);
  const [referencedWorkId, setReferencedWorkId] = useState(null);
  const [draft, setDraft] = useState("");
  const [uploading, setUploading] = useState(false);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  const loadWorks = useCallback(async () => {
    const result = await researchApi.listWorks();
    const rows = result.works || [];
    setWorks(rows);
    setSelectedWorkId((current) => current || rows[0]?.id || null);
    return rows;
  }, []);

  const loadSessions = useCallback(async () => {
    const result = await researchApi.listSessions();
    setSessions(result.sessions || []);
    return result.sessions || [];
  }, []);

  const loadLibrary = useCallback(async () => {
    const result = await researchApi.getLibrary();
    setLibraryWorks(result.works || []);
    return result.works || [];
  }, []);

  useEffect(() => {
    Promise.all([loadWorks(), loadSessions(), loadLibrary()]).then(async ([, rows]) => {
      if (rows.length) {
        setSessionId(rows[0].id);
      } else {
        const created = await researchApi.createSession();
        setSessions([created]);
        setSessionId(created.id);
      }
    }).catch((err) => setError(err.message));
  }, [loadWorks, loadSessions, loadLibrary]);

  useEffect(() => {
    if (!sessionId) return;
    researchApi.getSession(sessionId).then(setSession).catch((err) => setError(err.message));
  }, [sessionId]);

  useEffect(() => {
    if (!selectedWorkId) {
      setVersions([]);
      setSelectedArtifactId(null);
      return;
    }
    researchApi.listVersions(selectedWorkId).then((versionResult) => {
      const rows = versionResult.versions || [];
      setVersions(rows);
      const indexed = [...rows].reverse().find((version) => version.kind === "cleaned" && version.has_index);
      setChapterVersionId(indexed?.id || null);
      setSelectedArtifactId(null);
    }).catch((err) => setError(err.message));
  }, [selectedWorkId]);

  useEffect(() => {
    setSelectedChapterIndex(null);
    setChapterDetail(null);
    if (!selectedWorkId || !chapterVersionId) {
      setChapters([]);
      return;
    }
    researchApi.listChapters(selectedWorkId, chapterVersionId).then((result) => {
      setChapters(result.chapters || []);
    }).catch((err) => setError(err.message));
  }, [selectedWorkId, chapterVersionId]);

  useEffect(() => {
    if (!selectedWorkId || !chapterVersionId || selectedChapterIndex === null) return;
    researchApi.getChapter(selectedWorkId, chapterVersionId, selectedChapterIndex)
      .then(setChapterDetail).catch((err) => setError(err.message));
  }, [selectedWorkId, chapterVersionId, selectedChapterIndex]);

  const uploadFile = useCallback(async (file) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt")) {
      setError("第一版仅支持 TXT 文件");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const created = await researchApi.uploadWork(file);
      await loadWorks();
      setSelectedWorkId(created.job_id);
      setReferencedWorkId(created.job_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }, [loadWorks]);

  const createConversation = async () => {
    try {
      const created = await researchApi.createSession();
      setSessions((current) => [created, ...current]);
      setSessionId(created.id);
      setReferencedWorkId(null);
    } catch (err) {
      setError(err.message);
    }
  };

  const sendMessage = async () => {
    const message = draft.trim();
    if (!message || !sessionId || sending) return;
    setSending(true);
    setError("");
    try {
      await researchApi.sendMessage(sessionId, message, referencedWorkId, chapterReference);
      setDraft("");
      setReferencedWorkId(null);
      setChapterReference(null);
      setSession(await researchApi.getSession(sessionId));
      await loadSessions();
      if (selectedWorkId) {
        const versionResult = await researchApi.listVersions(selectedWorkId);
        setVersions(versionResult.versions || []);
      }
      await loadLibrary();
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  };

  const referencedWork = works.find((work) => work.id === referencedWorkId);
  const selectedArtifact = libraryWorks
    .flatMap((work) => work.artifacts || [])
    .find((artifact) => artifact.id === selectedArtifactId);

  const downloadVersion = async (version) => {
    try {
      const response = await authFetch(researchApi.downloadUrl(selectedWorkId, version.id));
      if (!response.ok) throw new Error("下载失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="relative flex h-screen flex-col bg-slate-50"
      onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false); }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); uploadFile(event.dataTransfer.files?.[0]); }}>
      {dragging && <div className="pointer-events-none absolute inset-0 z-50 flex items-center justify-center bg-indigo-950/40"><div className="rounded-3xl border-2 border-dashed border-white bg-indigo-600 px-16 py-14 text-2xl font-semibold text-white">松开鼠标，上传作品</div></div>}

      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-5">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/")} title="返回创作画布" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><ArrowLeft className="h-4 w-4" /></button>
          <BookOpen className="h-5 w-5 text-indigo-600" />
          <h1 className="font-semibold text-slate-800">小说研究</h1>
        </div>
        <button aria-label="新建对话" onClick={createConversation} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700"><Plus className="h-4 w-4" />新建对话</button>
      </header>
      {error && <div className="border-b border-red-100 bg-red-50 px-5 py-2 text-sm text-red-700">{error}</div>}

      <main className="flex min-h-0 flex-1">
        <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-700">作品库</h2>
            <button onClick={() => inputRef.current?.click()} disabled={uploading} className="rounded-lg p-2 text-indigo-600 hover:bg-indigo-50" title="上传作品">
              {uploading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            </button>
            <input ref={inputRef} className="hidden" type="file" accept=".txt,text/plain" onChange={(event) => { uploadFile(event.target.files?.[0]); event.target.value = ""; }} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {works.length ? works.map((work) => (
              <button key={work.id} onClick={() => { setSelectedWorkId(work.id); setReferencedWorkId((current) => current === work.id ? null : work.id); }}
                className={`mb-2 flex w-full items-center gap-3 rounded-xl border p-3 text-left ${selectedWorkId === work.id ? "border-indigo-300 bg-indigo-50" : "border-slate-200 hover:border-indigo-200"}`}>
                <FileText className="h-5 w-5 shrink-0 text-indigo-500" />
                <div className="min-w-0"><div className="truncate text-sm font-medium text-slate-700">{work.original_filename}</div><div className="mt-1 text-[11px] text-slate-400">点击后在下一条消息中引用</div></div>
              </button>
            )) : <button onClick={() => inputRef.current?.click()} className="w-full rounded-xl border border-dashed border-slate-300 px-4 py-8 text-sm text-slate-500">上传小说 TXT</button>}
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-5 py-3">
            <MessageSquarePlus className="h-4 w-4 text-indigo-500" />
            <select aria-label="切换对话" value={sessionId} onChange={(event) => { setSessionId(event.target.value); setReferencedWorkId(null); }} className="max-w-md flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700">
              {sessions.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-6">
            {session?.messages?.length ? <div className="mx-auto max-w-4xl space-y-5">{session.messages.map((message) => <Message key={message.id} message={message} />)}{sending && <div className="flex items-center gap-2 text-sm text-indigo-500"><LoaderCircle className="h-4 w-4 animate-spin" />正在阅读并分析……</div>}</div> : <div className="flex h-full items-center justify-center text-center"><div><Bot className="mx-auto mb-4 h-10 w-10 text-indigo-300" /><h2 className="font-semibold text-slate-700">开始一个独立研究对话</h2><p className="mt-2 text-sm text-slate-500">可以直接提问，也可以先点击左侧作品进行引用。</p></div></div>}
          </div>

          <div className="border-t border-slate-200 bg-white p-4">
            <div className="mx-auto max-w-4xl">
            {referencedWork && <div className="mb-2 inline-flex items-center gap-2 rounded-lg bg-indigo-50 px-3 py-1.5 text-xs text-indigo-700"><BookOpen className="h-3.5 w-3.5" />引用《{referencedWork.original_filename}》<button onClick={() => setReferencedWorkId(null)} title="取消引用"><X className="h-3.5 w-3.5" /></button></div>}
              {chapterReference && <div className="mb-2 ml-2 inline-flex items-center gap-2 rounded-lg bg-violet-50 px-3 py-1.5 text-xs text-violet-700"><FileText className="h-3.5 w-3.5" />引用章节：{chapterReference.heading}<button onClick={() => setChapterReference(null)} title="取消章节引用"><X className="h-3.5 w-3.5" /></button></div>}
              <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm focus-within:border-indigo-300">
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} rows={2} placeholder="输入研究问题……" className="min-h-[52px] flex-1 resize-none border-0 px-3 py-2 text-sm outline-none" />
                <button aria-label="发送" onClick={sendMessage} disabled={!draft.trim() || sending || !sessionId} className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-white disabled:opacity-40">{sending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button>
              </div>
            </div>
          </div>
        </section>

        <aside className="flex w-[400px] shrink-0 flex-col border-l border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3">
            <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
              <button aria-label="研究产出" onClick={() => setPanelTab("artifacts")} className={`flex-1 rounded-md px-2 py-1.5 text-xs ${panelTab === "artifacts" ? "bg-white font-semibold text-indigo-600 shadow-sm" : "text-slate-500"}`}>研究产出</button>
              <button aria-label="章节阅读" onClick={() => setPanelTab("chapters")} className={`flex-1 rounded-md px-2 py-1.5 text-xs ${panelTab === "chapters" ? "bg-white font-semibold text-indigo-600 shadow-sm" : "text-slate-500"}`}>章节阅读</button>
            </div>
            {versions.length > 0 && <div className="mt-3 flex flex-wrap gap-1.5">
              {versions.map((version) => <button key={version.id} onClick={() => downloadVersion(version)}
                className="flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-[11px] text-slate-500 hover:border-indigo-200 hover:text-indigo-600">
                <Download className="h-3 w-3" />
                {version.kind === "raw" ? "原始版" : `整理版 v${version.version_number}`}
                {version.active && <span className="text-indigo-500">当前</span>}
              </button>)}
            </div>}
          </div>
          {panelTab === "artifacts" ? <div className="grid min-h-0 flex-1 grid-rows-[minmax(160px,38%)_1fr]">
            <div className="overflow-y-auto border-b border-slate-100 p-2">
              {libraryWorks.length ? libraryWorks.map((work) => (
                <section key={work.id} className="mb-3 overflow-hidden rounded-xl border border-slate-200">
                  <button onClick={() => setSelectedWorkId(work.id)} className="flex w-full items-center gap-2 bg-slate-50 px-3 py-2 text-left">
                    <BookOpen className="h-3.5 w-3.5 text-indigo-500" />
                    <span className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-700">{work.original_filename}</span>
                    <span className="text-[10px] text-slate-400">{work.artifacts?.length || 0}</span>
                  </button>
                  <div className="p-1.5">
                    {work.artifacts?.length ? work.artifacts.map((artifact) => (
                      <button key={artifact.id} onClick={() => { setSelectedWorkId(work.id); setSelectedArtifactId(artifact.id); }}
                        className={`mb-1 w-full rounded-lg px-3 py-2 text-left ${selectedArtifactId === artifact.id ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50"}`}>
                        <div className="text-[10px] uppercase tracking-wide opacity-60">{artifact.artifact_type === "technique_card" ? "技法卡" : "研究报告"}</div>
                        <div className="mt-1 text-xs font-medium leading-5">{artifact.title}</div>
                      </button>
                    )) : <div className="px-3 py-4 text-center text-xs text-slate-400">暂无产出</div>}
                  </div>
                </section>
              )) : <div className="px-4 py-10 text-center text-xs leading-5 text-slate-400">还没有上传作品</div>}
            </div>
            <article className="min-h-0 overflow-y-auto p-5">
              {selectedArtifact ? <>
                <h3 className="mb-4 border-b border-slate-100 pb-3 font-semibold text-slate-800">{selectedArtifact.title}</h3>
                <div className="prose prose-slate max-w-none text-sm leading-7"><ReactMarkdown remarkPlugins={[remarkGfm, remarkHtmlBreaks]}>{selectedArtifact.content}</ReactMarkdown></div>
              </> : <div className="flex h-full items-center justify-center text-sm text-slate-400">选择一项产出查看正文</div>}
            </article>
          </div> : <div className="flex min-h-0 flex-1 flex-col">
            <div className="border-b border-slate-100 p-3">
              <select aria-label="整理版本" value={chapterVersionId || ""} onChange={(event) => setChapterVersionId(event.target.value || null)} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs">
                <option value="">选择已建立索引的整理版本</option>
                {versions.filter((version) => version.kind === "cleaned" && version.has_index).map((version) => <option key={version.id} value={version.id}>整理版 v{version.version_number}</option>)}
              </select>
            </div>
            <div className="grid min-h-0 flex-1 grid-cols-[140px_1fr]">
              <div className="overflow-y-auto border-r border-slate-100 p-2">
                {chapters.length ? chapters.map((chapter) => <button key={chapter.section_index} onClick={() => setSelectedChapterIndex(chapter.section_index)} className={`mb-1 w-full rounded-lg px-2 py-2 text-left text-xs ${selectedChapterIndex === chapter.section_index ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50"}`}>{chapter.heading}</button>) : <div className="px-2 py-6 text-center text-xs text-slate-400">该整理版本尚无章节索引</div>}
              </div>
              <article className="min-h-0 overflow-y-auto p-4">
                {chapterDetail ? <>
                  <div className="mb-3 flex items-center justify-between gap-2 border-b border-slate-100 pb-3">
                    <h3 className="text-sm font-semibold text-slate-800">{chapterDetail.heading}</h3>
                    <button aria-label="引用本章" onClick={() => {
                      setReferencedWorkId(selectedWorkId);
                      setChapterReference({ versionId: chapterVersionId, sectionIndex: chapterDetail.section_index, heading: chapterDetail.heading });
                    }} className="shrink-0 rounded-lg bg-violet-50 px-2 py-1 text-xs text-violet-700 hover:bg-violet-100">引用本章</button>
                  </div>
                  <div className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{chapterDetail.content}</div>
                </> : <div className="flex h-full items-center justify-center text-xs text-slate-400">选择章节查看完整正文</div>}
              </article>
            </div>
          </div>}
        </aside>
      </main>
    </div>
  );
}
