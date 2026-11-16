import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { IS_NATIVE_APP } from "../lib/runtime-config";
import { subscribeAppBack } from "../lib/appBackNavigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, BookOpen, Bot, Check, ChevronLeft, ChevronRight, Download, FileText, LoaderCircle, MessageSquare, Plus, Quote, Send, Upload, X } from "lucide-react";
import { researchApi } from "../lib/researchApi";
import { authFetch } from "../lib/authFetch";
import { remarkHtmlBreaks } from "../lib/markdown";
import "./ResearchPage.css";

const COVER_TONES = ["a", "b", "c"];

function coverGlyph(name) {
  return String(name || "书").replace(/\.txt$/i, "").slice(0, 1) || "书";
}

function versionLabel(version) {
  return version.kind === "raw" ? "原始版" : `整理版 v${version.version_number}`;
}

function cardExcerpt(content) {
  const text = String(content || "").replace(/\s+/g, " ").trim();
  if (text.length <= 48) return "";
  return `${text.slice(0, 72)}…`;
}

function Message({ message }) {
  const mine = message.role === "user";
  const body = (
    <>
      {message.referenced_works?.map((work) => (
        <div key={work.id} className={`mb-2 flex items-center gap-1.5 text-xs ${mine ? "text-blue-100" : "text-blue-600"}`}>
          <BookOpen className="h-3.5 w-3.5" />引用《{work.filename}》
        </div>
      ))}
      {message.chapter_reference && <div className={`mb-2 flex items-center gap-1.5 text-xs ${mine ? "text-blue-100" : "text-blue-600"}`}>
        <FileText className="h-3.5 w-3.5" />引用章节：{message.chapter_reference.heading}
      </div>}
      <div className={`prose max-w-none text-sm leading-7 ${mine ? "prose-invert text-inherit" : "prose-slate text-slate-800"}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm, remarkHtmlBreaks]}>{message.content}</ReactMarkdown>
      </div>
    </>
  );
  if (!mine) {
    return (
      <div className="rs-answer">
        <div className="rs-who"><span><Bot className="h-3.5 w-3.5" /></span>研究助手</div>
        {body}
      </div>
    );
  }
  return (
    <div className="flex justify-end">
      <div className="rs-user max-w-[86%] rounded-2xl rounded-br-md bg-blue-600 px-3.5 py-2.5 text-white">{body}</div>
    </div>
  );
}

export function ResearchPage({ appMode = IS_NATIVE_APP }) {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [works, setWorks] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [selectedWorkId, setSelectedWorkId] = useState(null);
  const [libraryWorks, setLibraryWorks] = useState([]);
  const [versions, setVersions] = useState([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState(null);
  const [panelTab, setPanelTab] = useState("chapters");
  const [versionPick, setVersionPick] = useState(null);
  const [readOpen, setReadOpen] = useState(true);
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

  useEffect(() => {
    if (!appMode) return undefined;
    let disposed = false;
    let unsubscribe;
    const handleBack = () => {
      if (selectedChapterIndex !== null) {
        setSelectedChapterIndex(null);
        return;
      }
      navigate("/");
    };
    subscribeAppBack(handleBack).then((remove) => {
      if (disposed) remove();
      else unsubscribe = remove;
    });
    return () => {
      disposed = true;
      unsubscribe?.();
    };
  }, [appMode, navigate, selectedChapterIndex]);

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
      setVersionPick(rows.find((version) => version.active)?.id || rows[0]?.id || null);
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

  const shelfWorks = [...works];
  libraryWorks.forEach((work) => {
    if (!shelfWorks.some((item) => item.id === work.id)) shelfWorks.push(work);
  });
  const openLibrary = libraryWorks.find((work) => work.id === selectedWorkId) || null;
  const techniqueCards = (openLibrary?.artifacts || []).filter((artifact) => artifact.artifact_type === "technique_card");
  const reportCards = (openLibrary?.artifacts || []).filter((artifact) => artifact.artifact_type !== "technique_card");
  const pickedVersion = versions.find((version) => version.id === versionPick) || null;
  const openName = shelfWorks.find((work) => work.id === selectedWorkId)?.original_filename || "";
  const chapterLines = chapterDetail ? chapterDetail.content.split(/\n+/).map((line) => line.trim()).filter(Boolean) : [];
  const chapterParagraphs = chapterLines[0] === chapterDetail?.heading ? chapterLines.slice(1) : chapterLines;
  const chooseVersion = (id) => {
    setVersionPick(id);
    const version = versions.find((item) => item.id === id);
    if (version?.kind === "cleaned" && version.has_index) setChapterVersionId(id);
  };
  const stepChapter = (delta) => {
    const index = chapters.findIndex((chapter) => chapter.section_index === selectedChapterIndex);
    const next = chapters[index + delta];
    if (next) setSelectedChapterIndex(next.section_index);
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
    <div className={`rs-app${readOpen ? "" : " rs-focus"}${appMode ? " is-native" : ""}`} data-reading={selectedChapterIndex === null ? "0" : "1"}
      onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false); }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); uploadFile(event.dataTransfer.files?.[0]); }}>
      {dragging && <div className="rs-dropmask"><div>松开鼠标，上传作品</div></div>}
      <input className="rs-pane" id="rs-chat" name="rs-pane" type="radio" defaultChecked />
      <input className="rs-pane" id="rs-shelf" name="rs-pane" type="radio" />
      <header className="rs-top">
        <button type="button" className="rs-icon" aria-label="返回创作画布" onClick={() => navigate("/")}><ArrowLeft size={18} /></button>
        <div className="rs-crumb"><small>文灵 /</small><h1>小说研究</h1></div>
        <span className="rs-sp" />
        <div className="rs-switch" aria-label="研究页面">
          <label htmlFor="rs-chat">对话</label>
          <label htmlFor="rs-shelf">书架</label>
        </div>
        <button type="button" className="rs-btn rs-upload" onClick={() => inputRef.current?.click()} disabled={uploading}>{uploading ? <LoaderCircle size={15} className="animate-spin" /> : <Upload size={15} />}上传作品</button>
        <button type="button" className="rs-btn rs-pri rs-create" onClick={createConversation}><Plus size={15} />新建对话</button>
      </header>
      {error && <div className="rs-error">{error}</div>}
      <div className="rs-body">
        <aside className="rs-side">
          <h5>{`书架 · ${shelfWorks.length}`}<button type="button" className="rs-mini" aria-label="上传到书架" onClick={() => inputRef.current?.click()}>{uploading ? <LoaderCircle size={14} className="animate-spin" /> : <Upload size={14} />}</button></h5>
          <div className="rs-books">
            {shelfWorks.map((work, index) => {
              const count = libraryWorks.find((item) => item.id === work.id)?.artifacts?.length || 0;
              return (
                <div key={work.id} className={`rs-book${selectedWorkId === work.id ? " is-on" : ""}`}>
                  <button type="button" className="rs-book-main" onClick={() => { setSelectedWorkId(work.id); setReadOpen(true); }}>
                    <i className={`rs-cover ${COVER_TONES[index % COVER_TONES.length]}`}>{coverGlyph(work.original_filename)}</i>
                    <span className="rs-book-name"><b>{work.original_filename}</b><small>{count ? `${count} 项产出` : "暂无产出"}</small></span>
                  </button>
                  <button type="button" className="rs-cite" aria-label={`引用 ${work.original_filename}`} aria-pressed={referencedWorkId === work.id} onClick={() => setReferencedWorkId(work.id)}>{referencedWorkId === work.id ? <><Check size={12} />已引用</> : "引用"}</button>
                </div>
              );
            })}
          </div>
          <button type="button" className="rs-drop" onClick={() => inputRef.current?.click()}><Upload size={14} />把 TXT 拖进页面即可上传</button>
          <input ref={inputRef} className="rs-file" type="file" accept=".txt,text/plain" onChange={(event) => { uploadFile(event.target.files?.[0]); event.target.value = ""; }} />
          <h5>{`对话 · ${sessions.length}`}<button type="button" className="rs-mini" aria-label="添加对话" onClick={createConversation}><Plus size={14} /></button></h5>
          <div className="rs-convs">
            {sessions.map((item) => (
              <button type="button" key={item.id} className={`rs-conv${item.id === sessionId ? " is-on" : ""}`} onClick={() => { setSessionId(item.id); setReferencedWorkId(null); }}><MessageSquare size={14} aria-hidden="true" />{item.title}</button>
            ))}
          </div>
        </aside>

        <section className="rs-chat">
          <div className="rs-chat-h">{session?.title || "研究对话"}</div>
          <div className="rs-thread">
            {session?.messages?.length ? <div className="rs-col">{session.messages.map((message) => <Message key={message.id} message={message} />)}{sending && <div className="rs-wait"><LoaderCircle size={16} className="animate-spin" />正在阅读并分析……</div>}</div> : <div className="rs-empty-chat"><Bot size={36} /><h2>开始一个独立研究对话</h2><p>先在书架里打开一本书，需要引用时再点「引用」。</p></div>}
          </div>
          <div className="rs-foot">
            <div className="rs-composer">
              {(referencedWork || chapterReference) && <div className="rs-refs">
                {referencedWork && <span className="rs-rc"><BookOpen size={13} />{referencedWork.original_filename}<button type="button" aria-label="取消引用" onClick={() => setReferencedWorkId(null)}><X size={12} /></button></span>}
                {chapterReference && <span className="rs-rc rs-rc-ch"><FileText size={13} />{chapterReference.heading}<button type="button" aria-label="取消章节引用" onClick={() => setChapterReference(null)}><X size={12} /></button></span>}
              </div>}
              <div className="rs-row">
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} rows={2} placeholder={session?.messages?.length ? "继续追问，或换一章来问…" : "输入研究问题……"} />
                <button type="button" className="rs-send" aria-label="发送" onClick={sendMessage} disabled={!draft.trim() || sending || !sessionId}>{sending ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}</button>
              </div>
            </div>
          </div>
        </section>

        <aside className="rs-read">
          <div className="rs-rd-h">
            <button type="button" className="rs-read-back" onClick={() => setSelectedChapterIndex(null)}><ArrowLeft size={16} />目录</button>
            {openName && <i className="rs-cover a rs-cover-sm">{coverGlyph(openName)}</i>}
            <b>{openName || "选择一本书"}</b>
            <span className="rs-sp" />
            {versions.length > 0 && <span className="rs-verwrap"><select className="rs-ver" aria-label="版本" value={versionPick || ""} onChange={(event) => chooseVersion(event.target.value)}>{versions.map((version) => <option key={version.id} value={version.id}>{versionLabel(version)}</option>)}</select>{pickedVersion?.active && <span className="rs-now">当前</span>}</span>}
            <button type="button" className="rs-icon" aria-label="下载当前版本" disabled={!pickedVersion} onClick={() => downloadVersion(pickedVersion)}><Download size={16} /></button>
            {selectedWorkId && <button type="button" className="rs-cite" aria-pressed={referencedWorkId === selectedWorkId} onClick={() => setReferencedWorkId(selectedWorkId)}>{referencedWorkId === selectedWorkId ? "已引用" : "引用"}</button>}
            <button type="button" className="rs-icon" aria-label="关闭阅读" onClick={() => setReadOpen(false)}><X size={16} /></button>
          </div>
          <div className="rs-tabs">
            <button type="button" aria-label="章节阅读" className={panelTab === "chapters" ? "is-on" : ""} onClick={() => setPanelTab("chapters")}>章节{chapters.length > 0 && <b>{chapters.length}</b>}</button>
            <button type="button" aria-label="研究产出" className={panelTab === "artifacts" ? "is-on" : ""} onClick={() => setPanelTab("artifacts")}>技法卡{techniqueCards.length > 0 && <b>{techniqueCards.length}</b>}</button>
            <button type="button" className={panelTab === "reports" ? "is-on" : ""} onClick={() => setPanelTab("reports")}>研究报告{reportCards.length > 0 && <b>{reportCards.length}</b>}</button>
          </div>
          <div className="rs-pane-body">
            <div className={panelTab === "chapters" ? "rs-ch" : "rs-ch rs-off"}>
              <div className="rs-toc">
                {chapters.length ? chapters.map((chapter) => <button type="button" key={chapter.section_index} className={selectedChapterIndex === chapter.section_index ? "is-on" : ""} onClick={() => setSelectedChapterIndex(chapter.section_index)}>{chapter.heading}</button>) : <div className="rs-empty">该整理版本尚无章节索引</div>}
              </div>
              <div className="rs-sheet">
                {chapterDetail ? <>
                  <div className="rs-sheet-body">
                    <h3>{chapterDetail.heading}</h3>
                    <div className="rs-meta">{openName}{pickedVersion ? ` · ${versionLabel(pickedVersion)}` : ""}</div>
                    {chapterParagraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
                  </div>
                  <div className="rs-bar">
                    <button type="button" className="rs-pbtn" aria-label="引用本章" onClick={() => {
                      setReferencedWorkId(selectedWorkId);
                      setChapterReference({ versionId: chapterVersionId, sectionIndex: chapterDetail.section_index, heading: chapterDetail.heading });
                    }}><Quote size={14} />引用本章到对话</button>
                    <span className="rs-sp" />
                    <button type="button" className="rs-pbtn rs-line" onClick={() => stepChapter(-1)} disabled={chapters[0]?.section_index === selectedChapterIndex}><ChevronLeft size={14} />上一章</button>
                    <button type="button" className="rs-pbtn rs-line" onClick={() => stepChapter(1)} disabled={chapters.at(-1)?.section_index === selectedChapterIndex}>下一章<ChevronRight size={14} /></button>
                  </div>
                </> : <div className="rs-empty">选择章节查看完整正文</div>}
              </div>
            </div>
            <div className={panelTab === "artifacts" ? "rs-cards" : "rs-cards rs-off"}>
              {selectedArtifact?.artifact_type === "technique_card" && <article className="rs-doc"><h3>{selectedArtifact.title}</h3><div className="rs-md"><ReactMarkdown remarkPlugins={[remarkGfm, remarkHtmlBreaks]}>{selectedArtifact.content}</ReactMarkdown></div></article>}
              {techniqueCards.length ? techniqueCards.map((artifact, index) => {
                const excerpt = cardExcerpt(artifact.content);
                return (
                <button type="button" key={artifact.id} className={`rs-tcard${selectedArtifactId === artifact.id ? " is-on" : ""}`} onClick={() => { setSelectedArtifactId(artifact.id); setPanelTab("artifacts"); }}>
                  <small>{`技法卡 · ${String(index + 1).padStart(2, "0")}`}</small>
                  <h4>{artifact.title}</h4>
                  {excerpt && <p>{excerpt}</p>}
                </button>
                );
              }) : <div className="rs-empty">还没有技法卡</div>}
            </div>
            <div className={panelTab === "reports" ? "rs-reps" : "rs-reps rs-off"}>
              {selectedArtifact && selectedArtifact.artifact_type !== "technique_card" && <article className="rs-doc"><h3>{selectedArtifact.title}</h3><div className="rs-md"><ReactMarkdown remarkPlugins={[remarkGfm, remarkHtmlBreaks]}>{selectedArtifact.content}</ReactMarkdown></div></article>}
              {reportCards.length ? reportCards.map((artifact) => {
                const excerpt = cardExcerpt(artifact.content);
                return (
                <button type="button" key={artifact.id} className={`rs-rep${selectedArtifactId === artifact.id ? " is-on" : ""}`} onClick={() => { setSelectedArtifactId(artifact.id); setPanelTab("reports"); }}>
                  <FileText size={16} />
                  <span><h4>{artifact.title}</h4>{excerpt && <p>{excerpt}</p>}</span>
                </button>
                );
              }) : <div className="rs-empty">还没有研究报告</div>}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
