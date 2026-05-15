import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BookOpen, GitBranch, Trash2, Calendar, Cpu, Bot } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";

const API_BASE = "http://127.0.0.1:9001/api";

export function DashboardPage() {
  const navigate = useNavigate();
  const [works, setWorks] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchWorks = async () => {
    try {
      const res = await fetch(`${API_BASE}/works`);
      if (res.ok) {
        const data = await res.json();
        setWorks(data);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWorks();
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("novel_token");
    localStorage.removeItem("novel_user");
    navigate("/login", { replace: true });
  };

  const handleDelete = async (e, workId) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm("确定删除这部作品？")) return;
    await fetch(`${API_BASE}/works/${workId}`, { method: "DELETE" });
    setWorks((prev) => prev.filter((w) => w.id !== workId));
  };

  const username = localStorage.getItem("novel_user") || "创作者";

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_right,_#bae6fd_0%,_#f8fafc_35%,_#e2e8f0_100%)] p-4 md:p-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <section className="rounded-2xl border border-slate-200 bg-white/80 p-6 shadow-sm backdrop-blur md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-medium uppercase tracking-[0.2em] text-sky-600">Novel Studio</p>
              <h1 className="mt-2 text-3xl font-semibold text-slate-900 md:text-4xl">欢迎回来，{username}</h1>
              <p className="mt-3 max-w-2xl text-sm text-slate-600 md:text-base">
                写一句话灵感，选几个标签，AI 直接帮你生成完整大纲。
              </p>
            </div>
            <div className="flex gap-3">
              <Button asChild>
                <Link to="/agent" className="flex items-center gap-1.5">
                  <Bot className="h-4 w-4" /> AI 写作助手
                </Link>
              </Button>
              <Button variant="outline" asChild>
                <Link to="/architecture" className="flex items-center gap-1.5">
                  <Cpu className="h-4 w-4" /> Agent 架构
                </Link>
              </Button>
              <Button variant="outline" onClick={handleLogout}>退出登录</Button>
            </div>
          </div>
        </section>

        {/* Works List */}
        {loading ? (
          <p className="text-center text-sm text-slate-500">加载中...</p>
        ) : works.length > 0 ? (
          <section className="grid gap-4 md:grid-cols-2">
            {works.map((work) => {
              const outline = work.outline_tree || {};
              const story = outline.story || {};
              const timeline = outline.timeline || [];
              const branches = outline.branches || [];
              const tags = work.tags || [];
              const createdDate = work.created_at ? new Date(work.created_at).toLocaleDateString("zh-CN") : "";

              return (
                <Link key={work.id} to={`/works/${work.id}`} className="block">
                  <Card className="h-full border-slate-200/80 bg-white/85 transition hover:-translate-y-0.5 hover:shadow-md">
                    <CardHeader>
                      <div className="flex items-start justify-between">
                        <CardTitle className="text-lg">{work.title}</CardTitle>
                        <button
                          onClick={(e) => handleDelete(e, work.id)}
                          className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500"
                          title="删除"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                      <CardDescription className="flex items-center gap-2">
                        <span>{story.genre || work.genre}</span>
                        {createdDate && (
                          <span className="flex items-center gap-1">
                            <Calendar className="h-3 w-3" /> {createdDate}
                          </span>
                        )}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {work.idea && (
                        <p className="text-sm text-slate-600 line-clamp-2">{work.idea}</p>
                      )}
                      <div className="flex items-center gap-3 text-xs text-slate-500">
                        <span className="flex items-center gap-1">
                          <GitBranch className="h-3 w-3" /> {timeline.length} 主线
                        </span>
                        <span>{branches.length} 支线</span>
                      </div>
                      {tags.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {tags.slice(0, 5).map((tag) => (
                            <span key={tag} className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700">
                              {tag}
                            </span>
                          ))}
                          {tags.length > 5 && (
                            <span className="text-[10px] text-slate-400">+{tags.length - 5}</span>
                          )}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </Link>
              );
            })}
          </section>
        ) : (
          <section className="flex flex-col items-center gap-6 rounded-2xl border border-dashed border-slate-300 bg-white/50 p-12 text-center">
            <BookOpen className="h-12 w-12 text-slate-300" />
            <div>
              <h2 className="text-lg font-semibold text-slate-700">还没有作品</h2>
              <p className="mt-1 text-sm text-slate-500">写一句话灵感，AI 帮你生成完整大纲</p>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
