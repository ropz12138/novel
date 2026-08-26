import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, User, Settings, LogOut, BookOpen } from "lucide-react";
import Canvas from "../components/Canvas";
import ModelConfigDialog from "../components/ModelConfigDialog";
import AgentChat from "../components/AgentChat";
import { fetchWorks, createWork, deleteWork } from "../lib/canvasApi";
import { useDebouncedRefresh } from "../hooks/useDebouncedRefresh";

const CHAT_WIDTH_STORAGE_KEY = "novel_canvas_chat_width";
const LAST_ACTIVE_WORK_STORAGE_KEY = "novel_canvas_last_active_work";
const DEFAULT_CHAT_WIDTH = 420;
const MIN_CHAT_WIDTH = 340;
const MAX_CHAT_WIDTH = 760;
const MIN_CANVAS_WIDTH = 520;

function clampChatWidth(width) {
  if (typeof window === "undefined") {
    return Math.min(MAX_CHAT_WIDTH, Math.max(MIN_CHAT_WIDTH, width));
  }
  const viewportWidth = window.innerWidth > 0
    ? window.innerWidth
    : MIN_CANVAS_WIDTH + DEFAULT_CHAT_WIDTH;
  const viewportMax = Math.max(MIN_CHAT_WIDTH, viewportWidth - MIN_CANVAS_WIDTH);
  return Math.min(Math.min(MAX_CHAT_WIDTH, viewportMax), Math.max(MIN_CHAT_WIDTH, width));
}

function getStoredChatWidth() {
  if (typeof window === "undefined") return DEFAULT_CHAT_WIDTH;
  const stored = Number(window.localStorage.getItem(CHAT_WIDTH_STORAGE_KEY));
  return Number.isFinite(stored) ? clampChatWidth(stored) : DEFAULT_CHAT_WIDTH;
}

export function CanvasPage() {
  const navigate = useNavigate();
  const [showChat, setShowChat] = useState(true);
  const [chatWidth, setChatWidth] = useState(getStoredChatWidth);
  const canvasRef = useRef(null);
  const [works, setWorks] = useState([]);
  const [currentWorkId, setCurrentWorkId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [worksError, setWorksError] = useState("");
  const [showWorkSelector, setShowWorkSelector] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showModelConfig, setShowModelConfig] = useState(false);
  const insertPillRef = useRef(null);

  const handleAddContext = useCallback((node, selectedText) => {
    insertPillRef.current?.(node.id, node.type, node.label, selectedText);
  }, []);

  useEffect(() => {
    loadWorks();
  }, []);

  const loadWorks = async () => {
    setWorksError("");
    try {
      const data = await fetchWorks();
      const loadedWorks = data.works || [];
      setWorks(loadedWorks);
      setCurrentWorkId((current) => {
        if (current && loadedWorks.some((work) => work.id === current)) {
          return current;
        }
        const lastActiveWorkId = window.localStorage.getItem(
          LAST_ACTIVE_WORK_STORAGE_KEY,
        );
        if (
          lastActiveWorkId
          && loadedWorks.some((work) => work.id === lastActiveWorkId)
        ) {
          return lastActiveWorkId;
        }
        return loadedWorks[0]?.id || null;
      });
    } catch (err) {
      console.error("Failed to load works:", err);
      setWorksError(err?.message || "加载作品失败");
    } finally {
      setLoading(false);
    }
  };

  const debouncedRefresh = useDebouncedRefresh(canvasRef, 300);

  const handleNodesUpdate = useCallback(() => {
    debouncedRefresh();
  }, [debouncedRefresh]);

  const handleCreateWork = async () => {
    const title = prompt("请输入作品名称：", "未命名作品");
    if (!title) return;

    try {
      const newWork = await createWork({ title });
      setWorks((prev) => [newWork, ...prev]);
      setCurrentWorkId(newWork.id);
      setShowWorkSelector(false);
    } catch (err) {
      console.error("Failed to create work:", err);
      alert("创建作品失败");
    }
  };

  const handleDeleteWork = async (e, workId) => {
    e.stopPropagation();
    if (!confirm("确定删除这部作品？所有节点和连线将被永久删除。")) return;

    try {
      await deleteWork(workId);
      setWorks((prev) => {
        const next = prev.filter((w) => w.id !== workId);
        setCurrentWorkId((current) => {
          if (current !== workId) return current;
          return next.length > 0 ? next[0].id : null;
        });
        return next;
      });
    } catch (err) {
      console.error("Failed to delete work:", err);
      alert("删除作品失败");
    }
  };

  const handleSelectWork = (workId) => {
    setCurrentWorkId(workId);
    setShowWorkSelector(false);
  };

  const handleLogout = () => {
    localStorage.removeItem("novel_token");
    localStorage.removeItem("novel_user");
    navigate("/login", { replace: true });
  };

  useEffect(() => {
    if (loading) return;
    if (currentWorkId) {
      window.localStorage.setItem(
        LAST_ACTIVE_WORK_STORAGE_KEY,
        currentWorkId,
      );
    } else {
      window.localStorage.removeItem(LAST_ACTIVE_WORK_STORAGE_KEY);
    }
  }, [currentWorkId, loading]);

  useEffect(() => {
    if (!showChat) return;
    window.localStorage.setItem(CHAT_WIDTH_STORAGE_KEY, String(Math.round(chatWidth)));
  }, [chatWidth, showChat]);

  useEffect(() => {
    const handleResize = () => {
      setChatWidth((width) => clampChatWidth(width));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const handleChatResizeStart = useCallback((event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = chatWidth;

    const handleMouseMove = (moveEvent) => {
      const delta = startX - moveEvent.clientX;
      setChatWidth(clampChatWidth(startWidth + delta));
    };

    const handleMouseUp = () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  }, [chatWidth]);

  const currentWork = works.find((w) => w.id === currentWorkId);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          <div className="text-sm text-gray-500">加载中...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-white">
      {worksError && (
        <div className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-2 text-center text-sm text-red-700">
          {worksError}
          <button type="button" className="ml-3 underline" onClick={loadWorks}>重试</button>
        </div>
      )}
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 px-4 py-2.5 bg-white">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xl">📚</span>
            <span className="text-base font-semibold text-slate-800">小说创作画布</span>
          </div>

          <div className="h-4 w-px bg-slate-200" />

          {/* 作品选择器 */}
          <div className="relative">
            <button
              onClick={() => setShowWorkSelector(!showWorkSelector)}
              className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg hover:bg-gray-100 transition-colors"
            >
              <span className="text-gray-500">作品:</span>
              <span className="font-medium text-gray-800">
                {currentWork ? currentWork.title : "请选择作品"}
              </span>
              <svg
                className={`w-4 h-4 text-gray-400 transition-transform ${
                  showWorkSelector ? "rotate-180" : ""
                }`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {showWorkSelector && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-white rounded-lg shadow-lg border border-gray-200 z-50">
                <div className="p-2 border-b border-gray-100">
                  <button
                    onClick={handleCreateWork}
                    className="w-full px-3 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 text-sm flex items-center justify-center gap-1"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    创建新作品
                  </button>
                </div>
                <div className="max-h-60 overflow-y-auto py-1">
                  {works.length === 0 ? (
                    <div className="px-4 py-6 text-center text-gray-500 text-sm">
                      暂无作品
                    </div>
                  ) : (
                    works.map((work) => (
                      <div
                        key={work.id}
                        onClick={() => handleSelectWork(work.id)}
                        className={`group flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50 transition-colors ${
                          currentWorkId === work.id ? "bg-blue-50" : ""
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-gray-400">📄</span>
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-gray-800 truncate">
                              {work.title}
                            </div>
                            <div className="text-[10px] text-gray-400">
                              {new Date(work.created_at).toLocaleDateString("zh-CN")}
                            </div>
                          </div>
                        </div>
                        <button
                          onClick={(e) => handleDeleteWork(e, work.id)}
                          className="p-1 text-gray-400 hover:text-red-500 opacity-70 group-hover:opacity-100 transition-opacity shrink-0"
                          title="删除作品"
                          aria-label={`删除作品 ${work.title}`}
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate("/research")}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-50 px-3 py-1.5 text-sm text-indigo-700 transition-colors hover:bg-indigo-100"
          >
            <BookOpen className="h-4 w-4" />
            <span>小说研究</span>
          </button>
          <button
            onClick={() => setShowChat(!showChat)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
              showChat
                ? "bg-blue-100 text-blue-700"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            <Bot className="h-4 w-4" />
            <span>{showChat ? "隐藏Agent" : "显示Agent"}</span>
          </button>
          <div className="relative">
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="flex items-center p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
              title="账户"
            >
              <User className="h-5 w-5 text-gray-600" />
            </button>
            {showUserMenu && (
              <div className="absolute top-full right-0 mt-1 w-44 bg-white rounded-lg shadow-lg border border-gray-200 z-50">
                <button
                  onClick={() => {
                    setShowUserMenu(false);
                    setShowModelConfig(true);
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-t-lg transition-colors"
                >
                  <Settings className="h-4 w-4" />
                  模型配置
                </button>
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 rounded-b-lg border-t border-gray-100 transition-colors"
                >
                  <LogOut className="h-4 w-4" />
                  退出登录
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-hidden flex">
        {!currentWorkId ? (
          <div className="flex-1 flex items-center justify-center bg-gray-50">
            <div className="text-center max-w-md">
              <div className="text-6xl mb-6">📖</div>
              <h2 className="text-xl font-semibold text-gray-800 mb-3">
                欢迎使用小说创作画布
              </h2>
              <p className="text-sm text-gray-500 mb-6">
                选择或创建一部作品，开始你的创作之旅
              </p>
              <button
                onClick={handleCreateWork}
                className="px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors flex items-center gap-2 mx-auto"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                创建新作品
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="min-w-0 flex-1 transition-all duration-300">
              <Canvas key={currentWorkId} ref={canvasRef} workId={currentWorkId} onAddContext={handleAddContext} />
            </div>
            {showChat && (
              <div
                className="relative shrink-0"
                style={{ width: chatWidth }}
              >
                <div
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="调整对话区域宽度"
                  title="拖拽调整对话区域宽度"
                  className="absolute inset-y-0 left-0 z-20 w-2 -translate-x-1 cursor-col-resize touch-none"
                  onMouseDown={handleChatResizeStart}
                >
                  <div className="mx-auto h-full w-px bg-gray-200 transition-colors hover:bg-blue-400" />
                </div>
                <AgentChat
                  workId={currentWorkId}
                  onNodesUpdate={handleNodesUpdate}
                  insertPillRef={insertPillRef}
                />
              </div>
            )}
          </>
        )}
      </main>

      <ModelConfigDialog
        open={showModelConfig}
        onClose={() => setShowModelConfig(false)}
      />
    </div>
  );
}
