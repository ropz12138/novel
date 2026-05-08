import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkles, Lightbulb, Tag, Loader2 } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Textarea } from "../components/ui/textarea";

const API_BASE = "http://127.0.0.1:9001/api";

const TAG_CATEGORIES = [
  {
    name: "题材",
    tags: ["修仙", "玄幻", "都市", "科幻", "仙侠", "历史", "言情", "悬疑", "末日", "游戏"],
  },
  {
    name: "风格",
    tags: ["热血", "爽文", "反转", "虐心", "轻喜", "权谋", "暗黑", "温馨"],
  },
  {
    name: "元素",
    tags: ["系统流", "重生", "穿越", "后宫", "升级流", "种田", "副本", "伏笔", "打脸", "扮猪吃虎"],
  },
  {
    name: "节奏",
    tags: ["快节奏", "慢热"],
  },
];

const EXAMPLE_IDEAS = [
  "一个废柴少年在修仙世界逆袭",
  "都市，主角有个读心术，和女警搭档破案",
  "星际，AI 叛乱，主角是唯一能控制 AI 的人",
  "重生回到高中，这次要追到校花",
  "全息游戏，被困在游戏里，死了就真死",
];

export function NewWorkPage() {
  const navigate = useNavigate();
  const [idea, setIdea] = useState("");
  const [selectedTags, setSelectedTags] = useState(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const toggleTag = (tag) => {
    setSelectedTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) {
        next.delete(tag);
      } else {
        next.add(tag);
      }
      return next;
    });
  };

  const handleGenerate = async () => {
    if (!idea.trim()) return;
    setError("");
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/works/generate-outline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idea: idea.trim(),
          tags: [...selectedTags],
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "请求失败" }));
        throw new Error(err.detail || "请求失败");
      }

      const data = await response.json();
      navigate(`/works/${data.work_id}`);
    } catch (err) {
      setError(err.message || "大纲生成失败");
    } finally {
      setLoading(false);
    }
  };

  const handleRandomExample = () => {
    const randomIndex = Math.floor(Math.random() * EXAMPLE_IDEAS.length);
    setIdea(EXAMPLE_IDEAS[randomIndex]);
  };

  return (
    <main className="min-h-screen bg-[linear-gradient(145deg,_#f8fafc_0%,_#ecfeff_45%,_#e2e8f0_100%)] p-4 md:p-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
        {/* Header */}
        <section className="flex items-center justify-between rounded-2xl border border-slate-200 bg-white/80 p-6 shadow-sm backdrop-blur">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">新建作品</h1>
            <p className="mt-1 text-sm text-slate-600">一句话灵感，AI 帮你展开成完整大纲</p>
          </div>
          <Button asChild variant="outline">
            <Link to="/dashboard">返回首页</Link>
          </Button>
        </section>

        {/* Input Section */}
        <Card className="border-slate-200/80 bg-white/90">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lightbulb className="h-5 w-5 text-yellow-500" />
              你的灵感
            </CardTitle>
            <CardDescription>
              随便写，不用想太多。AI 会帮你补全一切。
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="relative">
              <Textarea
                value={idea}
                onChange={(e) => setIdea(e.target.value)}
                placeholder="例如：一个废柴少年在修仙世界逆袭..."
                className="min-h-[100px] text-lg leading-relaxed pr-24"
              />
              <Button
                variant="ghost"
                size="sm"
                className="absolute right-2 bottom-2 text-xs text-slate-500 hover:text-slate-700"
                onClick={handleRandomExample}
              >
                随机示例
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Tags Section */}
        <Card className="border-slate-200/80 bg-white/90">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Tag className="h-5 w-5 text-purple-500" />
              选择元素
            </CardTitle>
            <CardDescription>
              可选。选了的元素会重点体现，不选则 AI 自由发挥。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {TAG_CATEGORIES.map((category) => (
              <div key={category.name} className="space-y-3">
                <h4 className="text-sm font-medium text-slate-700">{category.name}</h4>
                <div className="flex flex-wrap gap-2">
                  {category.tags.map((tag) => (
                    <button
                      key={tag}
                      onClick={() => toggleTag(tag)}
                      className={`rounded-full px-4 py-2 text-sm font-medium transition-all ${
                        selectedTags.has(tag)
                          ? "bg-purple-600 text-white shadow-md shadow-purple-200"
                          : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        {/* Generate Button */}
        <div className="flex justify-center">
          <Button
            size="lg"
            onClick={handleGenerate}
            disabled={!idea.trim() || loading}
            className="h-14 px-8 text-lg font-semibold"
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                AI 正在构思中...
              </>
            ) : (
              <>
                <Sparkles className="mr-2 h-5 w-5" />
                一键生成大纲
              </>
            )}
          </Button>
        </div>

        {/* Error Display */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-center text-red-600">
            {error}
          </div>
        )}
      </div>
    </main>
  );
}
