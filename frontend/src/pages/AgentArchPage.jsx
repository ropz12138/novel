import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  ArrowDown,
  ArrowRight,
  Brain,
  Search,
  PenTool,
  Save,
  Users,
  MessageSquare,
  Zap,
  Database,
  Radio,
} from "lucide-react";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../components/ui/card";

const FLOW = [
  { title: "Plan", desc: "规划节点 · LLM temp=0.6", color: "bg-blue-50 border-blue-200 text-blue-900" },
  { title: "Thinking", desc: "构思/标题/大纲提案", color: "bg-blue-50 border-blue-200 text-blue-900" },
  { title: "Query", desc: "按需或全量查询上下文", color: "bg-amber-50 border-amber-200 text-amber-900" },
  { title: "Write", desc: "正文生成 · LLM temp=0.7", color: "bg-emerald-50 border-emerald-200 text-emerald-900" },
  { title: "Save+Update", desc: "保存章节 + 更新角色", color: "bg-violet-50 border-violet-200 text-violet-900" },
];

function FlowNode({ title, desc, color }) {
  return (
    <div className={`w-full rounded-lg border px-3 py-2 ${color}`}>
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-xs opacity-80">{desc}</p>
    </div>
  );
}

function ArchitectureFlow() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-sky-200 bg-sky-50/70 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-sky-700">Supervisor 层</p>
        <div className="mt-2 grid gap-2 md:grid-cols-[1fr_auto_1fr] md:items-center">
          <div className="rounded-lg border border-sky-200 bg-white px-3 py-2">
            <p className="text-sm font-semibold text-slate-800">Supervisor Agent</p>
            <p className="mt-1 text-xs text-slate-600">LangGraph + Tool Calling</p>
          </div>
          <div className="flex justify-center text-sky-500">
            <ArrowRight className="h-4 w-4 hidden md:block" />
            <ArrowDown className="h-4 w-4 md:hidden" />
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <p className="text-sm font-semibold text-slate-800">路由决策</p>
            <p className="mt-1 text-xs text-slate-600">`dispatch_chapter` / `dispatch_evaluation` / 其他工具</p>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-700">Chapter 子流程</p>
        <div className="mt-3 grid gap-2">
          {FLOW.map((step, idx) => (
            <div key={step.title} className="flex flex-col items-center gap-2">
              <FlowNode {...step} />
              {idx < FLOW.length - 1 && <ArrowDown className="h-4 w-4 text-slate-400" />}
            </div>
          ))}
        </div>

        <div className="mt-4 grid gap-2 md:grid-cols-3">
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            Thinking 后需确认：`need_confirm(thinking/outline)`
          </div>
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            章节评估：由 `dispatch_evaluation` 派发给 EvaluationAgent
          </div>
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            Save 前需确认：`need_confirm(save)`
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── 阶段详情数据 ─── */
const STAGES = [
  {
    id: "plan",
    icon: Brain,
    color: "blue",
    bg: "bg-blue-50",
    border: "border-blue-200",
    iconColor: "text-blue-600",
    badge: "bg-blue-100 text-blue-700",
    title: "规划阶段 Plan",
    node: "plan_node",
    prompt: "agent_plan.txt",
    llm: { model: "ChatOpenAI", temperature: 0.6, streaming: true },
    description:
      "根据作品信息、大纲和用户指令先给出本章写作规划，作为后续构思输入。",
    inputs: [
      "作品信息 & 大纲树",
      "当前章节大纲",
      "前三章内容（各800字摘要）",
      "用户写作指令",
    ],
    outputs: ["写作规划（plan_text）"],
    sseEvents: ["stage_start", "plan_stream", "plan_done"],
  },
  {
    id: "thinking",
    icon: Brain,
    color: "blue",
    bg: "bg-blue-50",
    border: "border-blue-200",
    iconColor: "text-blue-600",
    badge: "bg-blue-100 text-blue-700",
    title: "构思阶段 Thinking",
    node: "thinking_node",
    prompt: "agent_thinking.txt",
    llm: { model: "ChatOpenAI", temperature: 0.8, streaming: true },
    description:
      "生成创意笔记、章节标题，并可选地提出大纲修改建议。使用高温度参数鼓励创意发散。",
    inputs: [
      "作品信息 & 大纲树",
      "当前章节大纲",
      "前三章内容（各800字摘要）",
      "用户写作指令",
      "规划结果（plan_text）",
    ],
    outputs: ["构思笔记（Markdown）", "章节标题", "大纲修改提案（可选）"],
    sseEvents: [
      "stage_start",
      "thinking_stream",
      "thinking_done",
      "title_proposed",
      "outline_proposal",
      "need_confirm",
    ],
  },
  {
    id: "query",
    icon: Search,
    color: "amber",
    bg: "bg-amber-50",
    border: "border-amber-200",
    iconColor: "text-amber-600",
    badge: "bg-amber-100 text-amber-700",
    title: "上下文收集 Query",
    node: "query_node",
    prompt: "无（纯数据库操作）",
    llm: null,
    description:
      "根据 thinking 阶段产出的 needed_queries 进行按需查询；缺省时回退到全量查询。",
    inputs: ["作品 ID", "当前章节号"],
    outputs: ["上下文包（context_pack）"],
    sseEvents: ["stage_start", "queries_needed", "query_result", "query_done"],
    details: [
      { icon: Database, label: "历史章节", desc: "所有已写章节，各600字摘要" },
      { icon: Database, label: "故事设定", desc: "标题、类型、卷信息" },
      { icon: Database, label: "伏笔管理", desc: "ID、内容、埋设/回收节点" },
      { icon: Database, label: "角色信息", desc: "首次出场≤当前章节的角色" },
    ],
  },
  {
    id: "write",
    icon: PenTool,
    color: "emerald",
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    iconColor: "text-emerald-600",
    badge: "bg-emerald-100 text-emerald-700",
    title: "写作阶段 Write",
    node: "write_node",
    prompt: "agent_write.txt",
    llm: { model: "ChatOpenAI", temperature: 0.7, streaming: true },
    description:
      "根据构思笔记和上下文包流式生成正文。质量评估已拆为独立 EvaluationAgent，由 Supervisor 按需派发。",
    inputs: [
      "故事信息 & 大纲树",
      "章节大纲 & 标题",
      "构思笔记",
      "上下文包",
      "历史章节",
    ],
    outputs: ["章节正文"],
    sseEvents: ["stage_start", "write_stream", "write_done"],
  },
  {
    id: "save",
    icon: Save,
    color: "violet",
    bg: "bg-violet-50",
    border: "border-violet-200",
    iconColor: "text-violet-600",
    badge: "bg-violet-100 text-violet-700",
    title: "保存 + 角色更新 Save & Update",
    node: "save_node → update_characters_node",
    prompt: "agent_update_characters.txt",
    llm: { model: "ChatOpenAI", temperature: 0.3, streaming: false },
    description:
      "将章节持久化到数据库，然后分析章节内容更新角色状态（当前状况、目标、位置）。",
    inputs: ["章节正文", "角色列表及当前状态"],
    outputs: ["Chapter 记录", "角色状态更新"],
    sseEvents: [
      "stage_start",
      "need_confirm",
      "saved",
      "characters_updated",
      "done",
    ],
  },
];

/* ─── SSE 事件对照表 ─── */
const SSE_EVENTS = [
  { event: "session_created", desc: "会话已创建", when: "Supervisor start 时" },
  { event: "supervisor_stream", desc: "统筹回复流式输出", when: "Supervisor LLM 输出块" },
  { event: "tool_calls", desc: "工具调用计划", when: "Supervisor 决定调用工具时" },
  { event: "tool_executed", desc: "工具节点执行", when: "LangGraph tools 节点处理后" },
  { event: "supervisor_done", desc: "统筹回复完成", when: "Supervisor 当前轮结束" },
  { event: "stage_start", desc: "阶段开始", when: "每个阶段启动时" },
  { event: "plan_stream", desc: "规划流式输出", when: "Plan LLM 输出块" },
  { event: "plan_done", desc: "规划完成", when: "Plan 结束" },
  { event: "thinking_stream", desc: "构思流式输出", when: "Thinking LLM 输出块" },
  { event: "thinking_done", desc: "构思完成", when: "Thinking 结束" },
  { event: "title_proposed", desc: "标题提案", when: "章节标题生成后" },
  { event: "outline_proposal", desc: "大纲修改提案", when: "提出大纲变更时" },
  { event: "outline_updated", desc: "大纲已更新", when: "大纲修改应用后" },
  { event: "queries_needed", desc: "按需查询指令", when: "Thinking 给出 needed_queries 时" },
  { event: "query_result", desc: "查询结果", when: "每项上下文加载完成" },
  { event: "query_done", desc: "查询完成", when: "所有上下文加载完毕" },
  { event: "write_stream", desc: "写作流式输出", when: "Write LLM 输出块" },
  { event: "write_done", desc: "写作完成", when: "章节正文生成完毕" },
  { event: "evaluation_done", desc: "独立评估完成", when: "EvaluationAgent 输出编辑/读者视角结果后" },
  { event: "need_confirm", desc: "等待确认", when: "需要用户决策时" },
  { event: "saved", desc: "已保存", when: "章节写入数据库后" },
  { event: "characters_updated", desc: "角色已更新", when: "角色状态更新后" },
  { event: "done", desc: "流程完成", when: "全部阶段执行完毕" },
  { event: "error", desc: "错误", when: "任意阶段出错时" },
];

/* ─── 颜色映射 ─── */
const COLOR_MAP = {
  blue: { ring: "ring-blue-200", text: "text-blue-700", dot: "bg-blue-500" },
  amber: { ring: "ring-amber-200", text: "text-amber-700", dot: "bg-amber-500" },
  emerald: { ring: "ring-emerald-200", text: "text-emerald-700", dot: "bg-emerald-500" },
  violet: { ring: "ring-violet-200", text: "text-violet-700", dot: "bg-violet-500" },
};

/* ─── 组件 ─── */
export function AgentArchPage() {
  const [activeStage, setActiveStage] = useState(null);

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_right,_#dbeafe_0%,_#f8fafc_35%,_#e2e8f0_100%)] p-4 md:p-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        {/* ─── 顶栏 ─── */}
        <section className="rounded-2xl border border-slate-200 bg-white/80 p-6 shadow-sm backdrop-blur md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" asChild className="gap-1 text-slate-500">
                  <Link to="/dashboard">
                    <ArrowLeft className="h-4 w-4" /> 返回
                  </Link>
                </Button>
              </div>
              <p className="mt-3 text-sm font-medium uppercase tracking-[0.2em] text-sky-600">
                Architecture
              </p>
              <h1 className="mt-2 text-3xl font-semibold text-slate-900 md:text-4xl">
                Agent 写作架构
              </h1>
              <p className="mt-3 max-w-2xl text-sm text-slate-600 md:text-base">
                当前实现为 Supervisor 统筹层 + Chapter 子流程。子流程包含 Plan / Thinking / Query /
                Write / Evaluate / Save 六阶段，并在关键节点保留人工确认。
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-700">
                <Zap className="h-3 w-3" /> LangChain + SSE
              </span>
              <span className="flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700">
                <Radio className="h-3 w-3" /> 流式输出
              </span>
            </div>
          </div>
        </section>

        {/* ─── React 流程图组件 ─── */}
        <Card className="border-slate-200/80 bg-white/85">
          <CardHeader>
            <CardTitle className="text-lg">工作流程图</CardTitle>
          </CardHeader>
          <CardContent>
            <ArchitectureFlow />
          </CardContent>
        </Card>

        {/* ─── 图例 ─── */}
        <div className="flex flex-wrap items-center justify-center gap-4 rounded-xl border border-slate-200 bg-white/80 px-6 py-3 text-xs">
          <span className="font-medium text-slate-500">图例：</span>
          {[
            { color: "bg-sky-50 border-sky-200", text: "Supervisor" },
            { color: "bg-blue-50 border-blue-200", text: "规划/构思" },
            { color: "bg-amber-50 border-amber-200", text: "查询" },
            { color: "bg-emerald-50 border-emerald-200", text: "写作" },
            { color: "bg-amber-50 border-amber-200", text: "评估" },
            { color: "bg-violet-50 border-violet-200", text: "保存/更新" },
            { color: "bg-red-50 border-red-200", text: "人工确认" },
          ].map((item) => (
            <span
              key={item.text}
              className={`flex items-center gap-1.5 rounded-md border px-2 py-1 ${item.color}`}
            >
              {item.text}
            </span>
          ))}
        </div>

        {/* ─── 阶段详情卡片 ─── */}
        <section>
          <h2 className="mb-4 text-xl font-semibold text-slate-800">阶段详情</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {STAGES.map((stage) => {
              const Icon = stage.icon;
              const colors = COLOR_MAP[stage.color];
              const isActive = activeStage === stage.id;

              return (
                <Card
                  key={stage.id}
                  className={`cursor-pointer border-slate-200/80 bg-white/85 transition-all hover:-translate-y-0.5 hover:shadow-md ${
                    isActive ? `ring-2 ${colors.ring}` : ""
                  }`}
                  onClick={() => setActiveStage(isActive ? null : stage.id)}
                >
                  <CardHeader className="pb-3">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-10 w-10 items-center justify-center rounded-lg ${stage.bg}`}
                      >
                        <Icon className={`h-5 w-5 ${stage.iconColor}`} />
                      </div>
                      <div>
                        <CardTitle className="text-base">{stage.title}</CardTitle>
                        <p className="mt-0.5 font-mono text-xs text-slate-400">
                          {stage.node}
                        </p>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-sm text-slate-600">{stage.description}</p>

                    {/* LLM 信息 */}
                    <div className="flex flex-wrap gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${stage.badge}`}>
                        {stage.prompt}
                      </span>
                      {stage.llm && (
                        <>
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                            temp={stage.llm.temperature}
                          </span>
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                            {stage.llm.streaming ? "流式" : "非流式"}
                          </span>
                        </>
                      )}
                      {!stage.llm && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                          无 LLM 调用
                        </span>
                      )}
                    </div>

                    {/* 展开详情 */}
                    {isActive && (
                      <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
                        {/* 输入 */}
                        <div>
                          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
                            输入
                          </p>
                          <ul className="space-y-0.5">
                            {stage.inputs.map((item) => (
                              <li
                                key={item}
                                className="flex items-center gap-1.5 text-xs text-slate-600"
                              >
                                <span className={`h-1.5 w-1.5 rounded-full ${colors.dot}`} />
                                {item}
                              </li>
                            ))}
                          </ul>
                        </div>
                        {/* 输出 */}
                        <div>
                          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
                            输出
                          </p>
                          <ul className="space-y-0.5">
                            {stage.outputs.map((item) => (
                              <li
                                key={item}
                                className="flex items-center gap-1.5 text-xs text-slate-600"
                              >
                                <CheckCircle className={`h-3 w-3 ${colors.text}`} />
                                {item}
                              </li>
                            ))}
                          </ul>
                        </div>
                        {/* Query 阶段的额外详情 */}
                        {stage.details && (
                          <div>
                            <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
                              数据来源
                            </p>
                            <div className="grid grid-cols-2 gap-2">
                              {stage.details.map((d) => {
                                const DetailIcon = d.icon;
                                return (
                                  <div
                                    key={d.label}
                                    className="flex items-start gap-2 rounded-md bg-slate-50 p-2"
                                  >
                                    <DetailIcon className="mt-0.5 h-3.5 w-3.5 text-slate-400" />
                                    <div>
                                      <p className="text-xs font-medium text-slate-700">
                                        {d.label}
                                      </p>
                                      <p className="text-[10px] text-slate-500">
                                        {d.desc}
                                      </p>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                        {/* SSE 事件 */}
                        <div>
                          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
                            SSE 事件
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {stage.sseEvents.map((evt) => (
                              <span
                                key={evt}
                                className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500"
                              >
                                {evt}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>

        {/* ─── SSE 事件对照表 ─── */}
        <Card className="border-slate-200/80 bg-white/85">
          <CardHeader>
            <div className="flex items-center gap-2">
              <MessageSquare className="h-5 w-5 text-slate-500" />
              <CardTitle className="text-lg">SSE 事件对照表</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="pb-2 pr-4 text-left font-semibold text-slate-600">
                      事件名
                    </th>
                    <th className="pb-2 pr-4 text-left font-semibold text-slate-600">
                      说明
                    </th>
                    <th className="pb-2 text-left font-semibold text-slate-600">
                      触发时机
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {SSE_EVENTS.map((evt, i) => (
                    <tr
                      key={evt.event}
                      className={i % 2 === 0 ? "bg-slate-50/50" : ""}
                    >
                      <td className="py-1.5 pr-4">
                        <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-violet-700">
                          {evt.event}
                        </code>
                      </td>
                      <td className="py-1.5 pr-4 text-slate-600">{evt.desc}</td>
                      <td className="py-1.5 text-slate-500">{evt.when}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* ─── 技术栈 ─── */}
        <Card className="border-slate-200/80 bg-white/85">
          <CardHeader>
            <CardTitle className="text-lg">技术栈</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
              {[
                {
                  icon: Brain,
                  label: "LLM 编排",
                  value: "LangChain + ChatOpenAI",
                  desc: "PromptTemplate + astream",
                },
                {
                  icon: Radio,
                  label: "实时通信",
                  value: "SSE (Server-Sent Events)",
                  desc: "asyncio.Queue + StreamingResponse",
                },
                {
                  icon: Database,
                  label: "状态持久化",
                  value: "PostgreSQL + SQLAlchemy",
                  desc: "AgentState JSONB checkpoint",
                },
                {
                  icon: Users,
                  label: "人工审核",
                  value: "Human-in-the-Loop",
                  desc: "confirm / reject / guide 三态",
                },
              ].map((item) => {
                const TechIcon = item.icon;
                return (
                  <div
                    key={item.label}
                    className="rounded-lg border border-slate-100 bg-slate-50/50 p-4"
                  >
                    <TechIcon className="h-5 w-5 text-slate-500" />
                    <p className="mt-2 text-xs font-medium uppercase tracking-wider text-slate-400">
                      {item.label}
                    </p>
                    <p className="mt-1 text-sm font-semibold text-slate-800">
                      {item.value}
                    </p>
                    <p className="mt-0.5 text-xs text-slate-500">{item.desc}</p>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
