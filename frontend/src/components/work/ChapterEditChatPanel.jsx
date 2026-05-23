import { API_BASE } from "../../lib/runtime-config";
import { authFetch } from "../../lib/authFetch";
import { useEffect, useRef, useState } from "react";
import { Check, Loader2, Send, X } from "lucide-react";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";


/**
 * Right-side panel: AI chat to revise chapter body (same API as legacy ChaptersPage).
 */
export function ChapterEditChatPanel({
  workId,
  chapterNum,
  contentDraft,
  setContentDraft,
  setTitleDraft,
}) {
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [proposal, setProposal] = useState(null);
  const chatEndRef = useRef(null);

  useEffect(() => {
    setChatMessages([]);
    setProposal(null);
    setChatInput("");
  }, [chapterNum]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, proposal]);

  const handleChatSend = async () => {
    if (!chatInput.trim() || chatSending || chapterNum == null) return;
    const userMsg = chatInput.trim();
    setChatInput("");
    setProposal(null);

    const newMessages = [...chatMessages, { role: "user", content: userMsg }];
    setChatMessages(newMessages);
    setChatSending(true);

    try {
      const res = await authFetch(`${API_BASE}/works/${workId}/chapters/${chapterNum}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMsg,
          history: chatMessages,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "对话失败" }));
        throw new Error(err.detail || "对话失败");
      }
      const data = await res.json();

      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.assistant_message },
      ]);

      if (data.proposed_content && data.proposed_content !== contentDraft) {
        setProposal({
          proposed_content: data.proposed_content,
          proposed_title: data.proposed_title,
          assistant_message: data.assistant_message,
        });
      }
    } catch (err) {
      setChatMessages((prev) => [...prev, { role: "assistant", content: `错误：${err.message}` }]);
    } finally {
      setChatSending(false);
    }
  };

  const handleAcceptProposal = () => {
    if (!proposal) return;
    setContentDraft(proposal.proposed_content);
    if (proposal.proposed_title) {
      setTitleDraft(proposal.proposed_title);
    }
    setProposal(null);
  };

  const handleRejectProposal = () => {
    setProposal(null);
  };

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <div className="space-y-3">
          {chatMessages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                  msg.role === "user" ? "bg-sky-600 text-white" : "bg-slate-100 text-slate-700"
                }`}
              >
                <p className="whitespace-pre-wrap">{msg.content}</p>
              </div>
            </div>
          ))}

          {proposal && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3">
              <p className="mb-2 text-xs font-medium text-blue-700">AI 修改建议</p>
              <p className="mb-3 text-xs text-slate-600">{proposal.assistant_message}</p>
              <div className="mb-3 max-h-[200px] overflow-y-auto rounded bg-white p-2 text-xs text-slate-700">
                <p className="line-clamp-[12] whitespace-pre-wrap">
                  {proposal.proposed_content.slice(0, 800)}
                  {proposal.proposed_content.length > 800 ? "..." : ""}
                </p>
                {proposal.proposed_content.length > 800 && (
                  <p className="mt-1 text-slate-400">
                    （共 {proposal.proposed_content.replace(/\s/g, "").length} 字，接受后显示全文）
                  </p>
                )}
              </div>
              {proposal.proposed_title && (
                <p className="mb-3 text-xs text-slate-500">
                  标题修改为：<span className="font-medium">{proposal.proposed_title}</span>
                </p>
              )}
              <div className="flex gap-2">
                <Button size="sm" className="h-7 text-xs" onClick={handleAcceptProposal}>
                  <Check className="mr-1 h-3 w-3" />
                  接受修改
                </Button>
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={handleRejectProposal}>
                  <X className="mr-1 h-3 w-3" />
                  拒绝
                </Button>
              </div>
            </div>
          )}

          {chatSending && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-xl bg-slate-100 px-3 py-2 text-sm text-slate-500">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                AI 正在思考...
              </div>
            </div>
          )}
        </div>
        <div ref={chatEndRef} />
      </div>

      <div className="shrink-0 border-t border-slate-200 px-4 py-3">
        <div className="flex items-end gap-2">
          <Textarea
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            placeholder="输入修改指令..."
            className="min-h-[40px] max-h-[120px] resize-none text-sm"
            rows={1}
            disabled={chapterNum == null}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleChatSend();
              }
            }}
          />
          <Button
            size="sm"
            className="h-10 shrink-0"
            onClick={handleChatSend}
            disabled={chatSending || !chatInput.trim() || chapterNum == null}
          >
            {chatSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}
