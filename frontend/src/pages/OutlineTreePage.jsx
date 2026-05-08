import { Link } from "react-router-dom";
import { Clock3, GitBranch, Milestone } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";

function SideNode({ text, direction, chapterStart, chapterEnd }) {
  const align = direction === "left" ? "items-end pr-4" : "items-start pl-4";
  const color = direction === "left" ? "border-cyan-300 bg-cyan-50" : "border-indigo-300 bg-indigo-50";

  return (
    <div className={`flex ${align}`}>
      <div className={`max-w-[240px] rounded-md border px-2 py-1 text-xs text-slate-700 ${color}`}>
        <p>{text}</p>
        <p className="mt-1 text-[11px] text-slate-500">第{chapterStart}-{chapterEnd}章</p>
      </div>
    </div>
  );
}

export function OutlineTreePage() {
  const raw = localStorage.getItem("novel_outline_tree");
  const fallbackTitle = localStorage.getItem("novel_story_title") || "未命名作品";
  const fallbackGenre = localStorage.getItem("novel_story_genre") || "未分类";

  let tree = null;
  try {
    tree = raw ? JSON.parse(raw) : null;
  } catch {
    tree = null;
  }

  const timeline = tree?.timeline || [];
  const branches = tree?.branches || [];
  const story = tree?.story || { title: fallbackTitle, genre: fallbackGenre, volume: "第一卷" };

  return (
    <main className="min-h-screen bg-[linear-gradient(160deg,_#f8fafc_0%,_#ecfeff_55%,_#e2e8f0_100%)] p-4 md:p-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <section className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white/80 p-5 shadow-sm backdrop-blur">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">发展/时间节点大纲</h1>
            <p className="mt-1 text-sm text-slate-600">
              <span className="font-medium">{story.title}</span> · {story.genre} · {story.volume}
            </p>
          </div>
          <div className="flex gap-2">
            <Button asChild variant="outline">
              <Link to="/works/new">返回编辑</Link>
            </Button>
            <Button asChild>
              <Link to="/dashboard">回首页</Link>
            </Button>
          </div>
        </section>

        <Card className="border-slate-200/80 bg-white/90">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <GitBranch size={18} /> 时间轴结构
            </CardTitle>
            <CardDescription>每个节点展示：发展节点、时间节点、章节区间。</CardDescription>
          </CardHeader>
          <CardContent>
            {timeline.length === 0 ? (
              <p className="text-sm text-slate-600">暂无可展示数据，请先返回“新建作品”生成大纲。</p>
            ) : (
              <div className="space-y-4">
                {timeline
                  .slice()
                  .sort((a, b) => a.order - b.order)
                  .map((node, idx, arr) => (
                    <div key={node.id} className="rounded-xl border border-slate-200 bg-white p-4">
                      <div className="grid grid-cols-[1fr_auto_1fr] gap-2">
                        <div className="space-y-2">
                          {branches
                            .filter((s) => s.attach_to === node.id && s.side === "left")
                            .map((side) => (
                              <SideNode
                                key={side.id}
                                text={side.name}
                                direction="left"
                                chapterStart={side.chapter_start}
                                chapterEnd={side.chapter_end}
                              />
                            ))}
                        </div>

                        <div className="flex min-w-[310px] flex-col items-center gap-2 px-2">
                          <div className="flex w-full items-center justify-between rounded-lg border border-sky-300 bg-sky-50 px-3 py-2 text-xs">
                            <span className="flex items-center gap-1 font-medium text-sky-900">
                              <Milestone size={14} /> 发展节点
                            </span>
                            <span className="ml-3 text-right text-slate-700">{node.development_node}</span>
                          </div>

                          <div className="flex w-full items-center justify-between rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs">
                            <span className="flex items-center gap-1 font-medium text-amber-900">
                              <Clock3 size={14} /> 时间节点
                            </span>
                            <span className="text-slate-700">{node.time_node}</span>
                          </div>

                          <div className="rounded-md bg-slate-900 px-2 py-1 text-xs text-white">
                            第{node.chapter_start}-{node.chapter_end}章
                          </div>
                          {idx < arr.length - 1 ? <div className="h-4 w-px bg-slate-300" /> : null}
                        </div>

                        <div className="space-y-2">
                          {branches
                            .filter((s) => s.attach_to === node.id && s.side === "right")
                            .map((side) => (
                              <SideNode
                                key={side.id}
                                text={side.name}
                                direction="right"
                                chapterStart={side.chapter_start}
                                chapterEnd={side.chapter_end}
                              />
                            ))}
                        </div>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
