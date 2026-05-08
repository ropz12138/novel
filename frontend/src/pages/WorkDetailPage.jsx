import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  Calendar,
  Loader2,
  Plus,
  Send,
  Tag as TagIcon,
  Trash2,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";

const API_BASE = "http://127.0.0.1:9001/api";

/* ────────────────────────── Editable text helper ────────────────────────── */

function EditableText({ value, onSave, className = "", multiline = false }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const ref = useRef(null);

  useEffect(() => {
    if (editing && ref.current) {
      ref.current.focus();
      ref.current.select();
    }
  }, [editing]);

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== value) {
      onSave(trimmed);
    } else {
      setDraft(value);
    }
    setEditing(false);
  };

  if (!editing) {
    return (
      <span
        className={`cursor-pointer hover:bg-slate-100 rounded px-1 transition-colors ${className}`}
        onClick={() => { setDraft(value); setEditing(true); }}
        title="点击编辑"
      >
        {value}
      </span>
    );
  }

  if (multiline) {
    return (
      <Textarea
        ref={ref}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
          if (e.key === "Escape") { setDraft(value); setEditing(false); }
        }}
        className={`min-h-[60px] ${className}`}
      />
    );
  }

  return (
    <Input
      ref={ref}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") { setDraft(value); setEditing(false); }
      }}
      className={className}
    />
  );
}

/* ─────────────────────────── Branch Card ─────────────────────────────── */

function BranchCard({ branch, onUpdate, onDelete }) {
  const isLeft = branch.side === "left";
  const borderColor = isLeft ? "border-amber-300" : "border-violet-300";
  const bgColor = isLeft ? "bg-amber-50" : "bg-violet-50";
  const badgeColor = isLeft ? "bg-amber-100 text-amber-800" : "bg-violet-100 text-violet-800";

  return (
    <article className={`rounded-xl border ${borderColor} ${bgColor} px-3 py-2 shadow-sm group`}>
      <div className="mb-1 flex items-center justify-between">
        <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${badgeColor}`}>支线</span>
        <button onClick={onDelete} className="hidden rounded p-0.5 text-slate-400 hover:bg-red-50 hover:text-red-500 group-hover:block" title="删除支线">
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
      <EditableText value={branch.name} onSave={(val) => onUpdate("name", val)} className="text-[11px] font-medium leading-4 text-slate-800" />
      <p className="mt-1 text-[10px] text-slate-500">第{branch.chapter_start}-{branch.chapter_end}章</p>
    </article>
  );
}

/* ─────────────────────────── Outline Tree ─────────────────────────────── */

function InlineTree({ tree, onUpdateNode, onDeleteNode, onAddBranch }) {
  const timeline = tree?.timeline || [];
  const branches = tree?.branches || [];

  if (!timeline.length) {
    return <p className="text-sm text-slate-600">暂无大纲数据。</p>;
  }

  return (
    <div className="relative mx-auto w-full max-w-[860px] rounded-2xl border border-slate-200 bg-white px-6 pb-10 pt-8 shadow-[0_18px_45px_rgba(15,23,42,0.08)]">
      {/* "时间线" label */}
      <div className="absolute left-1/2 top-4 z-[10] -translate-x-1/2 rounded-full bg-slate-900 px-3 py-1 text-[10px] text-white">时间线 ↓</div>

      {/* Vertical timeline line - runs behind all rows */}
      <div className="absolute bottom-8 left-1/2 top-12 z-[1] w-1 -translate-x-1/2 rounded-full bg-gradient-to-b from-blue-600 to-violet-600" />

      <div className="relative z-[2] mt-10 space-y-6">
        {timeline.slice().sort((a, b) => a.order - b.order).map((node, idx) => {
          const leftBranches = branches.filter((s) => s.attach_to === node.id && s.side === "left");
          const rightBranches = branches.filter((s) => s.attach_to === node.id && s.side === "right");

          return (
            <section key={node.id} className="group/row flex items-center min-h-[88px]">
              {/* ── Left column: branch cards + connector line ── */}
              <div className="flex flex-1 items-center min-w-0">
                {leftBranches.length > 0 && (
                  <>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      {leftBranches.map((b) => (
                        <BranchCard key={b.id} branch={b} onUpdate={(field, val) => onUpdateNode(b.id, { [field]: val })} onDelete={() => onDeleteNode(b.id)} />
                      ))}
                    </div>
                    <span className="block h-[2px] flex-1 bg-slate-200" />
                  </>
                )}
              </div>

              {/* ── Center: main node + half-circle add buttons ── */}
              <div className="relative shrink-0">
                {/* Left add button: half-circle flush to left edge → slides out to full circle on hover */}
                <button
                  onClick={() => onAddBranch(node.id, "left")}
                  className="absolute left-0 top-1/2 z-[2] flex h-[20px] w-[20px] -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-amber-300 bg-amber-50 text-amber-600 transition-all hover:bg-amber-200 group-hover/row:-translate-x-full group-hover/row:z-[5]"
                  title="添加左侧支线"
                >
                  <Plus className="h-3 w-3 opacity-0 transition-opacity group-hover/row:opacity-100" />
                </button>

                <article className="relative z-[3] w-[220px] rounded-xl border-2 border-blue-600 bg-white px-3 py-2 shadow-[0_8px_20px_rgba(15,23,42,0.08)] group">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700">主线 {String(idx + 1).padStart(2, "0")}</span>
                    <button onClick={() => onDeleteNode(node.id)} className="hidden rounded p-0.5 text-slate-400 hover:bg-red-50 hover:text-red-500 group-hover:block" title="删除节点"><Trash2 className="h-3 w-3" /></button>
                  </div>
                  <EditableText value={node.development_node} onSave={(val) => onUpdateNode(node.id, { development_node: val })} className="text-[11px] font-semibold leading-4 text-slate-800" multiline />
                  <div className="mt-1 flex items-center gap-1 text-[10px] text-slate-500">
                    <EditableText value={node.time_node} onSave={(val) => onUpdateNode(node.id, { time_node: val })} className="text-[10px] text-slate-500" />
                    <span>· 第</span>
                    <EditableText value={`${node.chapter_start}`} onSave={(val) => onUpdateNode(node.id, { chapter_start: parseInt(val, 10) || 1 })} className="w-8 text-[10px] text-slate-500" />
                    <span>-</span>
                    <EditableText value={`${node.chapter_end}`} onSave={(val) => onUpdateNode(node.id, { chapter_end: parseInt(val, 10) || 10 })} className="w-8 text-[10px] text-slate-500" />
                    <span>章</span>
                  </div>
                </article>

                {/* Right add button: half-circle flush to right edge → slides out to full circle on hover */}
                <button
                  onClick={() => onAddBranch(node.id, "right")}
                  className="absolute right-0 top-1/2 z-[2] flex h-[20px] w-[20px] -translate-y-1/2 translate-x-1/2 items-center justify-center rounded-full border border-violet-300 bg-violet-50 text-violet-600 transition-all hover:bg-violet-200 group-hover/row:translate-x-full group-hover/row:z-[5]"
                  title="添加右侧支线"
                >
                  <Plus className="h-3 w-3 opacity-0 transition-opacity group-hover/row:opacity-100" />
                </button>
              </div>

              {/* ── Right column: connector line + branch cards ── */}
              <div className="flex flex-1 items-center min-w-0">
                {rightBranches.length > 0 && (
                  <>
                    <span className="block h-[2px] flex-1 bg-slate-200" />
                    <div className="flex shrink-0 flex-col items-start gap-1">
                      {rightBranches.map((b) => (
                        <BranchCard key={b.id} branch={b} onUpdate={(field, val) => onUpdateNode(b.id, { [field]: val })} onDelete={() => onDeleteNode(b.id)} />
                      ))}
                    </div>
                  </>
                )}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}

/* ─────────────────────────── Chat Panel ───────────────────────────────── */

function ChatPanel({ workId, onOutlineUpdated }) {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "你好，我是你的大纲助手。你可以用自然语言指挥我修改大纲，比如：\n- 「在主线 3 后加一个反派暗杀的支线」\n- 「把第二阶段的章节改成 20-30 章」\n- 「把作品名改成星辰大海」",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const content = input.trim();
    if (!content || loading) return;

    const userMsg = { role: "user", content };
    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/works/${workId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: content, history: messages.slice(1) }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "请求失败" }));
        throw new Error(err.detail || "请求失败");
      }

      const data = await res.json();
      setMessages([...nextMessages, { role: "assistant", content: data.assistant_message }]);

      if (data.outline_tree) {
        onOutlineUpdated(data.outline_tree);
      }
    } catch (err) {
      setMessages([...nextMessages, { role: "assistant", content: `错误：${err.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((msg, idx) => (
          <div key={idx} className={`max-w-[90%] rounded-lg px-3 py-2 text-sm leading-6 whitespace-pre-wrap ${msg.role === "user" ? "ml-auto bg-sky-600 text-white" : "bg-slate-100 text-slate-700"}`}>
            {msg.content}
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" /> AI 正在思考...
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="border-t border-slate-200 p-3">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
            placeholder="输入修改指令..."
            disabled={loading}
          />
          <Button size="sm" onClick={handleSend} disabled={!input.trim() || loading}>
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── Main Page ────────────────────────────────── */

export function WorkDetailPage() {
  const { workId } = useParams();
  const [work, setWork] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [outlineTree, setOutlineTree] = useState(null);
  const [saving, setSaving] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);

  useEffect(() => {
    const fetchWork = async () => {
      try {
        const res = await fetch(`${API_BASE}/works/${workId}`);
        if (!res.ok) throw new Error("加载失败");
        const data = await res.json();
        setWork(data);
        setOutlineTree(data.outline_tree);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchWork();
  }, [workId]);

  const saveOutline = async (tree) => {
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/works/${workId}/outline`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outline_tree: tree }),
      });
      if (res.ok) {
        const data = await res.json();
        setWork(data);
      }
    } catch { /* silently fail */ } finally {
      setSaving(false);
    }
  };

  const handleUpdateNode = (nodeId, fields) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      for (const list of [next.timeline, next.branches, next.foreshadowing]) {
        const node = list?.find((n) => n.id === nodeId);
        if (node) { Object.assign(node, fields); break; }
      }
      saveOutline(next);
      return next;
    });
  };

  const handleDeleteNode = (nodeId) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      next.timeline = (next.timeline || []).filter((n) => n.id !== nodeId);
      next.branches = (next.branches || []).filter((n) => n.id !== nodeId);
      next.foreshadowing = (next.foreshadowing || []).filter((n) => n.id !== nodeId);
      saveOutline(next);
      return next;
    });
  };

  const handleAddBranch = (attachTo, side) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      next.branches = [...(next.branches || []), {
        id: `B${Date.now()}`, attach_to: attachTo, side, name: "新支线", summary: "", chapter_start: 1, chapter_end: 10,
      }];
      saveOutline(next);
      return next;
    });
  };

  const handleUpdateStory = (field, value) => {
    setOutlineTree((prev) => {
      const next = structuredClone(prev);
      next.story = next.story || {};
      next.story[field] = value;
      saveOutline(next);
      return next;
    });
  };

  if (loading) {
    return <main className="flex min-h-screen items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-slate-400" /></main>;
  }

  if (error || !work) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="space-y-4 text-center">
          <p className="text-red-500">{error || "作品不存在"}</p>
          <Button asChild variant="outline"><Link to="/dashboard">返回首页</Link></Button>
        </div>
      </main>
    );
  }

  const story = outlineTree?.story || {};
  const tags = work.tags || [];
  const createdDate = work.created_at ? new Date(work.created_at).toLocaleDateString("zh-CN") : "";

  return (
    <main className="flex h-screen flex-col bg-[linear-gradient(145deg,_#f8fafc_0%,_#ecfeff_45%,_#e2e8f0_100%)]">
      {/* Top bar */}
      <section className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-6 py-3 backdrop-blur">
        <div className="flex items-center gap-4">
          <Button asChild variant="ghost" size="sm">
            <Link to="/dashboard"><ArrowLeft className="mr-1 h-4 w-4" /> 返回</Link>
          </Button>
          <div>
            <h1 className="text-lg font-semibold text-slate-900">
              <EditableText value={story.title || work.title} onSave={(val) => handleUpdateStory("title", val)} className="text-lg font-semibold text-slate-900" />
            </h1>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <EditableText value={story.genre || work.genre} onSave={(val) => handleUpdateStory("genre", val)} className="text-xs text-slate-500" />
              {story.volume && <span>· {story.volume}</span>}
              {createdDate && <span className="flex items-center gap-1"><Calendar className="h-3 w-3" /> {createdDate}</span>}
              {saving && <span className="text-xs text-slate-400">保存中...</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {tags.length > 0 && (
            <div className="flex items-center gap-1">
              <TagIcon className="h-3 w-3 text-purple-500" />
              {tags.slice(0, 4).map((tag) => (
                <span key={tag} className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700">{tag}</span>
              ))}
            </div>
          )}
          <Button asChild variant="outline" size="sm">
            <Link to={`/works/${workId}/agent/1`}>
              <BookOpen className="mr-1 h-4 w-4" /> Agent 写作
            </Link>
          </Button>
          <Button variant={chatOpen ? "default" : "outline"} size="sm" onClick={() => setChatOpen(!chatOpen)}>
            {chatOpen ? "关闭对话" : "AI 对话"}
          </Button>
        </div>
      </section>

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 overflow-auto p-6">
          {work.idea && (
            <div className="mb-4 rounded-lg border border-slate-200 bg-white/80 p-3 text-sm text-slate-600">
              <span className="font-medium text-slate-800">灵感：</span>{work.idea}
            </div>
          )}
          <InlineTree tree={outlineTree} onUpdateNode={handleUpdateNode} onDeleteNode={handleDeleteNode} onAddBranch={handleAddBranch} />
        </div>

        {chatOpen && (
          <div className="w-[380px] shrink-0 border-l border-slate-200 bg-white">
            <ChatPanel workId={workId} onOutlineUpdated={(newTree) => setOutlineTree(newTree)} />
          </div>
        )}
      </div>
    </main>
  );
}
