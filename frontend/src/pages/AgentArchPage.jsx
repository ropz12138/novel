import { Link } from "react-router-dom";
import {
  ArrowDown,
  ArrowLeft,
  Bot,
  Brain,
  ClipboardList,
  Cpu,
  Database,
  FileSearch,
  GitBranch,
  Layers,
  PenTool,
  Radio,
  Route,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  Workflow,
  Wrench,
} from "lucide-react";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../components/ui/card";

const supervisorTools = [
  { name: "query_characters", desc: "结构化查询角色卡，支持按姓名、角色类型、状态等过滤。" },
  { name: "query_chapters", desc: "查询章节号、标题、状态、字数和正文预览。" },
  { name: "count_chapter_words", desc: "计算指定章节正文纯文字数。" },
  { name: "query_chapter_meta", desc: "读取章节摘要、关键情节、伏笔、事实等元数据概览。" },
  { name: "grep_chapter_meta", desc: "在章节元数据字段中按关键词检索。" },
  { name: "grep", desc: "在角色设定和章节正文中搜索关键词上下文。" },
  { name: "read_outline", desc: "读取作品当前完整大纲。" },
  { name: "query_outline_related_chapters", desc: "按大纲节点或关键词级联查找关联章节。" },
  { name: "read_chapter", desc: "读取指定章节范围的完整正文和基础信息。" },
  { name: "query_characters_by_chapter", desc: "查询目标章节上下文内相关角色状态。" },
  { name: "grep_in_chapter", desc: "在指定章节范围正文内检索关键词。" },
  { name: "query_chapter_outline", desc: "读取指定章节范围对应的大纲节点。" },
  { name: "query_previous_chapters", desc: "读取目标章节前文，用于续写或编辑上下文。" },
  { name: "query_foreshadowing", desc: "查询作品伏笔及其埋设、回收位置。" },
  { name: "read_work_context", desc: "读取作品标题、类型、卷、时间线数量等基础上下文。" },
  { name: "read_chat_history", desc: "读取当前 Supervisor 会话最近对话。" },
  { name: "analyze_requirements", desc: "分析用户需求，生成澄清问题和可持久化 todolist。" },
  { name: "read_requirements_doc", desc: "读取当前作品长期需求文档。" },
  { name: "update_requirements_doc", desc: "全量覆盖写入长期需求文档。" },
  { name: "update_task_status", desc: "手动更新 task_items 中的任务状态。" },
  { name: "update_todolist_readiness", desc: "标记任务清单是否已具备执行条件。" },
  { name: "execute_todo_task", desc: "执行 todolist 单项任务，并自动路由到对应子 Agent。" },
  { name: "read_todolist", desc: "读取当前会话任务清单、状态、依赖和执行信息。" },
];

const childTodoTools = [
  { name: "create_child_todolist", desc: "为当前父任务创建子任务清单。" },
  { name: "read_child_todolist", desc: "读取当前父任务下的子任务进度。" },
  { name: "update_child_task_status", desc: "更新子任务状态和执行摘要。" },
];

const agents = [
  {
    name: "OutlineAgent",
    icon: GitBranch,
    status: "todo harness: dispatch_outline",
    purpose: "创建新大纲，或编辑已有大纲、角色、大纲关联章节。",
    tools: [
      ...childTodoTools,
      { name: "read_outline", desc: "读取当前完整大纲，编辑前的基线数据。" },
      { name: "query_outline_characters", desc: "查询作品角色设定，用于角色相关大纲修改。" },
      { name: "query_outline_related_chapters", desc: "按大纲线索回查关联章节和元数据。" },
      { name: "generate_outline", desc: "从创意和标签一次性生成并保存完整大纲。" },
      { name: "edit_outline_by_suggestion", desc: "按自然语言建议执行大纲编辑，可 dry-run 或自动应用。" },
      { name: "commit_or_rollback", desc: "自动模式下提交或回滚大纲事务。" },
      { name: "read_requirements_doc", desc: "读取长期写作要求，约束大纲创建或修改。" },
    ],
  },
  {
    name: "ChapterAgent",
    icon: PenTool,
    status: "todo harness: dispatch_chapter",
    purpose: "统一处理新章节撰写和已有章节编辑。",
    tools: [
      ...childTodoTools,
      { name: "query_outline", desc: "读取作品信息和大纲摘要。" },
      { name: "query_chapter_outline", desc: "读取目标章节的大纲节点。" },
      { name: "query_previous_chapters", desc: "读取前文作为续写上下文。" },
      { name: "query_characters", desc: "读取全部角色设定和当前状态。" },
      { name: "query_foreshadowing", desc: "读取伏笔信息，辅助埋设或回收。" },
      { name: "generate_chapter_content", desc: "仅创建下一章正文，并自动保存和同步元数据。" },
      { name: "save_chapter", desc: "保存或覆盖章节正文。" },
      { name: "update_characters_after_chapter", desc: "根据已保存正文更新角色状态、目标和位置。" },
      { name: "read_chapter", desc: "读取已有章节完整正文。" },
      { name: "query_characters_by_chapter", desc: "查询目标章节相关角色上下文。" },
      { name: "grep_in_chapter", desc: "在章节正文中按关键词定位片段。" },
      { name: "query_chapter_meta", desc: "读取章节元数据概览。" },
      { name: "grep_chapter_meta", desc: "在章节元数据中搜索关键词。" },
      { name: "generate_patch_edit", desc: "生成局部 JSON 补丁并自动保存正文修改。" },
      { name: "rewrite_chapter", desc: "全量重写已有章节并自动保存。" },
      { name: "overwrite_chapter_title", desc: "只覆盖章节标题，不修改正文。" },
      { name: "sync_chapter_metadata", desc: "按当前正文重新生成章节元数据。" },
      { name: "count_chapter_words", desc: "统计指定章节字数。" },
      { name: "read_requirements_doc", desc: "读取长期写作要求，约束章节生成和编辑。" },
    ],
  },
  {
    name: "EvaluationAgent",
    icon: FileSearch,
    status: "todo harness: dispatch_evaluation",
    purpose: "从编辑、读者和大纲同步性角度评估章节质量。",
    tools: [
      ...childTodoTools,
      { name: "read_chapter_for_eval", desc: "读取待评估章节正文。" },
      { name: "read_chapter_outline_for_eval", desc: "读取待评估章节的大纲节点。" },
      { name: "read_previous_chapters_for_eval", desc: "读取前文，用于连贯性判断。" },
      { name: "evaluate_as_editor", desc: "以编辑视角给出质量问题和修改建议。" },
      { name: "evaluate_as_reader", desc: "以读者视角评估可读性、爽点和期待感。" },
      { name: "evaluate_chapter_outline_sync", desc: "评估正文、元数据和大纲是否同步。" },
    ],
  },
  {
    name: "WritingExpertAgent",
    icon: Sparkles,
    status: "已实现；dispatch_writing_expert 未挂入 ALL_TOOLS",
    purpose: "针对冲突、钩子、节奏、人物张力、对话等问题提供微咨询。",
    tools: [
      { name: "query_writing_library", desc: "查询写作技巧库中匹配题材和问题类型的技巧。" },
      { name: "generate_advice", desc: "生成候选建议、推荐方案和可交给 ChapterAgent 的改写指令。" },
    ],
  },
];

const directDispatchTools = [
  { name: "dispatch_outline", desc: "兼容入口，派发大纲任务；当前主链路由 execute_todo_task 间接路由。" },
  { name: "dispatch_chapter", desc: "兼容入口，派发章节撰写或编辑；todolist 场景禁止直接调用。" },
  { name: "dispatch_evaluation", desc: "兼容入口，派发章节评估；当前主链路由 execute_todo_task 间接路由。" },
  { name: "dispatch_writing_expert", desc: "写作专家派发入口已定义，但未加入 Supervisor 的 ALL_TOOLS。" },
];

const toolCategories = [
  {
    name: "查询/读取",
    desc: "只读上下文检索，供 Supervisor 或子 Agent 决策前收集资料。",
    tools: [
      "query_characters",
      "query_chapters",
      "read_outline",
      "read_chapter",
      "query_chapter_outline",
      "query_previous_chapters",
      "query_foreshadowing",
      "query_chapter_meta",
      "grep",
      "grep_in_chapter",
      "grep_chapter_meta",
    ],
  },
  {
    name: "需求/任务管理",
    desc: "把用户需求转成可执行任务，并维护任务清单状态。",
    tools: [
      "analyze_requirements",
      "read_todolist",
      "execute_todo_task",
      "update_task_status",
      "update_todolist_readiness",
      "create_child_todolist",
      "read_child_todolist",
      "update_child_task_status",
    ],
  },
  {
    name: "大纲生成/编辑",
    desc: "创建作品大纲、编辑大纲字段、角色和事务提交。",
    tools: [
      "generate_outline",
      "edit_outline_by_suggestion",
      "query_outline_characters",
      "query_outline_related_chapters",
      "commit_or_rollback",
    ],
  },
  {
    name: "章节生成/编辑",
    desc: "生成新章、覆盖保存、局部编辑、全量重写和标题修改。",
    tools: [
      "generate_chapter_content",
      "save_chapter",
      "generate_patch_edit",
      "rewrite_chapter",
      "overwrite_chapter_title",
      "sync_chapter_metadata",
      "update_characters_after_chapter",
      "count_chapter_words",
    ],
  },
  {
    name: "评估/咨询",
    desc: "评估章节质量、正文与大纲同步性，以及提供写作技巧建议。",
    tools: [
      "evaluate_as_editor",
      "evaluate_as_reader",
      "evaluate_chapter_outline_sync",
      "query_writing_library",
      "generate_advice",
    ],
  },
  {
    name: "长期记忆/偏好",
    desc: "读取和更新作品级长期需求文档。",
    tools: ["read_requirements_doc", "update_requirements_doc"],
  },
];

const stats = [
  { label: "Supervisor 工具", value: supervisorTools.length, icon: Wrench },
  { label: "主链路子 Agent", value: 3, icon: Bot },
  { label: "已实现子 Agent", value: agents.length, icon: Brain },
  { label: "执行入口", value: "execute_todo_task", icon: ClipboardList },
];

function ToolList({ tools }) {
  return (
    <ul className="mt-3 grid gap-2 md:grid-cols-2">
      {tools.map((tool) => (
        <li
          key={tool.name}
          className="rounded-md border border-slate-200 bg-white px-3 py-2"
        >
          <code className="text-xs font-semibold text-slate-900">{tool.name}</code>
          <p className="mt-1 text-xs leading-5 text-slate-600">{tool.desc}</p>
        </li>
      ))}
    </ul>
  );
}

function AgentNode({ agent }) {
  const Icon = agent.icon;

  return (
    <li className="relative pl-6 before:absolute before:left-0 before:top-0 before:h-full before:border-l before:border-slate-200">
      <div className="absolute left-0 top-6 h-px w-4 bg-slate-200" />
      <Card className="border-slate-200 bg-white">
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-slate-900 text-white">
                <Icon className="h-5 w-5" />
              </span>
              <div>
                <CardTitle className="text-base text-slate-900">{agent.name}</CardTitle>
                <p className="mt-1 text-sm text-slate-600">{agent.purpose}</p>
              </div>
            </div>
            <span className="w-fit rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600">
              {agent.status}
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <ToolList tools={agent.tools} />
        </CardContent>
      </Card>
    </li>
  );
}

function CategoryCard({ category }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="text-sm font-semibold text-slate-900">{category.name}</p>
      <p className="mt-1 text-xs leading-5 text-slate-600">{category.desc}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {category.tools.map((tool) => (
          <code
            key={tool}
            className="rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-700"
          >
            {tool}
          </code>
        ))}
      </div>
    </div>
  );
}

function FlowArrow({ label, accent = false }) {
  const lineColor = accent ? "bg-indigo-300" : "bg-slate-300";
  const iconColor = accent ? "text-indigo-400" : "text-slate-400";
  return (
    <div className="flex flex-col items-center py-1.5">
      <div className={`h-4 w-px ${lineColor}`} />
      {label ? (
        <span
          className={`my-0.5 rounded-full border px-2 py-0.5 text-[11px] ${
            accent
              ? "border-indigo-200 bg-indigo-50 text-indigo-700"
              : "border-slate-200 bg-white text-slate-500"
          }`}
        >
          {label}
        </span>
      ) : null}
      <div className={`h-4 w-px ${lineColor}`} />
      <ArrowDown className={`h-4 w-4 ${iconColor}`} />
    </div>
  );
}

const diagramTagStyles = {
  outline: "border-emerald-200 bg-emerald-50 text-emerald-700",
  chapter: "border-sky-200 bg-sky-50 text-sky-700",
  evaluation: "border-amber-200 bg-amber-50 text-amber-700",
  expert: "border-slate-200 bg-slate-100 text-slate-500",
};

function DiagramAgentNode({ agent, dispatch, tagKey, muted = false }) {
  const Icon = agent.icon;
  return (
    <div
      className={`flex h-full flex-col rounded-lg border p-3 shadow-sm ${
        muted ? "border-dashed border-slate-300 bg-slate-50" : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-white ${
            muted ? "bg-slate-400" : "bg-slate-900"
          }`}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900">{agent.name}</p>
          {dispatch ? (
            <code className={`mt-0.5 inline-block rounded border px-1 text-[10px] ${diagramTagStyles[tagKey]}`}>
              {dispatch}
            </code>
          ) : null}
        </div>
      </div>
      <p className="mt-2 text-[11px] leading-4 text-slate-500">{agent.purpose}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        {agent.tools.map((tool) => (
          <code
            key={tool.name}
            title={tool.desc}
            className="cursor-help rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-600"
          >
            {tool.name}
          </code>
        ))}
      </div>
    </div>
  );
}

const supervisorEntryTools = [
  { name: "analyze_requirements", desc: "把用户需求拆成可执行的 todolist。" },
  { name: "execute_todo_task", desc: "执行单项任务并经 harness 路由到子 Agent。" },
  { name: "read_todolist", desc: "读取任务清单与状态。" },
  { name: "update_task_status", desc: "更新任务状态。" },
];

function ArchDiagram() {
  const mainAgents = [
    { agent: agents[0], dispatch: "dispatch_outline", tagKey: "outline" },
    { agent: agents[1], dispatch: "dispatch_chapter", tagKey: "chapter" },
    { agent: agents[2], dispatch: "dispatch_evaluation", tagKey: "evaluation" },
  ];

  return (
    <Card className="border-slate-200 bg-white">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Workflow className="h-5 w-5 text-slate-600" />
          <CardTitle className="text-lg">整体架构图</CardTitle>
        </div>
        <p className="text-sm text-slate-500">
          自上而下的执行链路：用户 → Supervisor → Harness 控制层 → 子 Agent。子 Agent 工具悬停可见功能说明。
        </p>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <div className="mx-auto flex min-w-[680px] flex-col items-center">
            {/* 用户层 */}
            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-4 py-2">
              <Users className="h-4 w-4 text-slate-500" />
              <span className="text-sm font-medium text-slate-700">用户 / 前端对话（SSE 流式）</span>
            </div>

            <FlowArrow label="用户消息" />

            {/* Supervisor 层 */}
            <div className="w-full rounded-xl border border-indigo-200 bg-indigo-50/60 p-4">
              <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-md bg-indigo-700 text-white">
                    <Bot className="h-5 w-5" />
                  </span>
                  <div>
                    <p className="text-base font-semibold text-indigo-950">SupervisorAgent</p>
                    <p className="text-xs text-indigo-700">
                      LangGraph 循环：agent 节点决定 tool calls → tools 节点执行 → 直到无工具调用
                    </p>
                  </div>
                </div>
                <span className="w-fit rounded-md border border-indigo-200 bg-white px-2 py-1 text-[11px] text-indigo-700">
                  绑定 {supervisorTools.length} 个工具
                </span>
              </div>

              <div className="mt-3 grid gap-2 md:grid-cols-2">
                <div className="rounded-md border border-indigo-200 bg-white p-2">
                  <p className="text-[11px] font-semibold text-indigo-900">工具类别（按用途）</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {toolCategories.map((c) => (
                      <span
                        key={c.name}
                        title={c.desc}
                        className="cursor-help rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-700"
                      >
                        {c.name}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="rounded-md border border-indigo-200 bg-white p-2">
                  <p className="text-[11px] font-semibold text-indigo-900">核心执行入口</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {supervisorEntryTools.map((t) => (
                      <code
                        key={t.name}
                        title={t.desc}
                        className="cursor-help rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-700"
                      >
                        {t.name}
                      </code>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <FlowArrow label="execute_todo_task 进入执行层" accent />

            {/* Harness 层 */}
            <div className="w-full rounded-xl border-2 border-indigo-300 bg-indigo-50 p-4">
              <div className="mb-2 flex items-center justify-center gap-2">
                <Route className="h-4 w-4 text-indigo-700" />
                <p className="text-sm font-semibold text-indigo-950">
                  Harness 控制层 · Supervisor 与子 Agent 之间的必经关卡
                </p>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <div className="rounded-md border border-indigo-200 bg-white p-3">
                  <div className="flex items-center gap-2">
                    <ClipboardList className="h-4 w-4 text-indigo-700" />
                    <p className="text-sm font-semibold text-indigo-900">todo_harness.py（执行控制）</p>
                  </div>
                  <p className="mt-1 text-[11px] leading-4 text-indigo-700">
                    解析任务 → 校验依赖 → 锁定状态（pending/in_progress/completed/failed） → 推断 dispatch_tool →
                    路由子 Agent → 结果写回 task_items。
                  </p>
                </div>
                <div className="rounded-md border border-indigo-200 bg-white p-3">
                  <div className="flex items-center gap-2">
                    <Cpu className="h-4 w-4 text-indigo-700" />
                    <p className="text-sm font-semibold text-indigo-900">runtime_harness.py（运行时控制）</p>
                  </div>
                  <p className="mt-1 text-[11px] leading-4 text-indigo-700">
                    生命周期(before/after/on_error) · 上下文注入 · 工具策略校验 · active_child 管理 · 恢复 · 可观测性。
                  </p>
                </div>
              </div>
            </div>

            {/* 三路 dispatch 箭头 */}
            <div className="grid w-full grid-cols-3 gap-2">
              {mainAgents.map(({ dispatch, tagKey }) => (
                <div key={dispatch} className="flex flex-col items-center py-1.5">
                  <div className="h-4 w-px bg-indigo-300" />
                  <code className={`my-0.5 rounded border px-1.5 py-0.5 text-[10px] ${diagramTagStyles[tagKey]}`}>
                    {dispatch}
                  </code>
                  <div className="h-4 w-px bg-indigo-300" />
                  <ArrowDown className="h-4 w-4 text-indigo-400" />
                </div>
              ))}
            </div>

            {/* 子 Agent 层 */}
            <div className="grid w-full gap-3 md:grid-cols-3">
              {mainAgents.map(({ agent, dispatch, tagKey }) => (
                <DiagramAgentNode key={agent.name} agent={agent} dispatch={dispatch} tagKey={tagKey} />
              ))}
            </div>

            {/* 未接入子 Agent */}
            <div className="mt-3 w-full">
              <div className="mb-1 flex items-center gap-2">
                <div className="h-px flex-1 bg-slate-200" />
                <span className="text-[11px] text-slate-400">已实现 · 未挂入 ALL_TOOLS（当前不可达）</span>
                <div className="h-px flex-1 bg-slate-200" />
              </div>
              <DiagramAgentNode agent={agents[3]} dispatch="dispatch_writing_expert" tagKey="expert" muted />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function AgentArchPage() {
  return (
    <main className="min-h-screen bg-slate-50 p-4 md:p-8">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm md:p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <Button variant="ghost" size="sm" asChild className="mb-3 gap-1 text-slate-500">
                <Link to="/dashboard">
                  <ArrowLeft className="h-4 w-4" /> 返回
                </Link>
              </Button>
              <p className="text-sm font-medium uppercase tracking-[0.18em] text-slate-500">
                Agent Architecture
              </p>
              <h1 className="mt-2 text-3xl font-semibold text-slate-950 md:text-4xl">
                Supervisor Agent 架构
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">
                当前实现是 Supervisor 绑定查询、需求分析、任务状态和 todolist 工具；执行型任务先生成
                todolist，再由 <code className="rounded bg-slate-100 px-1">execute_todo_task</code> 通过
                harness 路由到子 Agent。
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 md:w-[420px]">
              {stats.map((item) => {
                const Icon = item.icon;
                return (
                  <div key={item.label} className="rounded-md border border-slate-200 bg-slate-50 p-3">
                    <Icon className="h-4 w-4 text-slate-500" />
                    <p className="mt-2 text-xs text-slate-500">{item.label}</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{item.value}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <ArchDiagram />

        <div className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Route className="h-5 w-5 text-slate-600" />
                <CardTitle className="text-lg">Harness 的位置</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 text-sm text-slate-700">
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <p className="font-semibold text-slate-900">SupervisorAgent</p>
                  <p className="mt-1 text-xs leading-5 text-slate-600">
                    面向用户对话，负责理解需求、查询上下文、生成 todolist，并调用执行入口。
                  </p>
                </div>
                <div className="rounded-md border border-indigo-200 bg-indigo-50 p-3">
                  <p className="font-semibold text-indigo-950">todo_harness.py（执行控制）</p>
                  <p className="mt-1 text-xs leading-5 text-indigo-800">
                    位于 Supervisor 和子 Agent 之间，是任务执行控制层：校验依赖、锁定状态、推断 dispatch_tool、
                    调用对应子 Agent，并把结果写回 task_items。
                  </p>
                </div>
                <div className="rounded-md border border-indigo-200 bg-indigo-50 p-3">
                  <p className="font-semibold text-indigo-950">runtime_harness.py（运行时控制）</p>
                  <p className="mt-1 text-xs leading-5 text-indigo-800">
                    包裹整次运行：生命周期(before/after/on_error)、上下文注入、工具策略校验、active_child 管理、
                    会话恢复与可观测性。
                  </p>
                </div>
                <div className="grid gap-2 md:grid-cols-3">
                  {["OutlineAgent", "ChapterAgent", "EvaluationAgent"].map((name) => (
                    <div key={name} className="rounded-md border border-slate-200 bg-white p-3 text-xs font-semibold text-slate-800">
                      {name}
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Layers className="h-5 w-5 text-slate-600" />
                <CardTitle className="text-lg">工具分类</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2">
                {toolCategories.map((category) => (
                  <CategoryCard key={category.name} category={category} />
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="border-slate-200 bg-white">
          <CardHeader>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-slate-600" />
              <CardTitle className="text-lg">Supervisor 直接可用工具</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <ToolList tools={supervisorTools} />
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white">
          <CardHeader>
            <div className="flex items-center gap-2">
              <GitBranch className="h-5 w-5 text-slate-600" />
              <CardTitle className="text-lg">子 Agent 树</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-indigo-700 text-white">
                  <Bot className="h-5 w-5" />
                </span>
                <div>
                  <p className="text-base font-semibold text-slate-950">SupervisorAgent</p>
                  <p className="mt-1 text-sm leading-6 text-slate-600">
                    LangGraph 循环：agent 节点决定 tool calls，tools 节点执行，直到不再调用工具。
                  </p>
                </div>
              </div>
              <div className="relative mt-5 pl-6 before:absolute before:left-0 before:top-0 before:h-full before:border-l before:border-indigo-200">
                <div className="absolute left-0 top-6 h-px w-4 bg-indigo-200" />
                <div className="rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2">
                  <p className="text-sm font-semibold text-indigo-950">todo_harness 执行层</p>
                  <p className="mt-1 text-xs leading-5 text-indigo-800">
                    由 <code>execute_todo_task</code> 进入，负责依赖校验、状态流转、任务路由和结果落库；子 Agent 不直接暴露给用户。
                  </p>
                </div>
              </div>
              <ul className="mt-5 space-y-4">
                {agents.map((agent) => (
                  <AgentNode key={agent.name} agent={agent} />
                ))}
              </ul>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <div className="flex items-center gap-2">
                <ClipboardList className="h-5 w-5 text-slate-600" />
                <CardTitle className="text-lg">执行路由</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3 text-sm text-slate-700">
                <li className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <span className="font-semibold">1. analyze_requirements</span>
                  <p className="mt-1 text-xs leading-5 text-slate-600">
                    将用户请求转成 task_items，推断 owner、task_type 和 dispatch_tool。
                  </p>
                </li>
                <li className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <span className="font-semibold">2. execute_todo_task</span>
                  <p className="mt-1 text-xs leading-5 text-slate-600">
                    校验依赖，维护 pending / in_progress / completed / failed 状态。
                  </p>
                </li>
                <li className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <span className="font-semibold">3. todo_harness 内部路由</span>
                  <p className="mt-1 text-xs leading-5 text-slate-600">
                    dispatch_outline 到 OutlineAgent，dispatch_chapter 到 ChapterAgent，dispatch_evaluation 到 EvaluationAgent。
                  </p>
                </li>
              </ol>
            </CardContent>
          </Card>

          <Card className="border-slate-200 bg-white">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Radio className="h-5 w-5 text-slate-600" />
                <CardTitle className="text-lg">兼容/未暴露入口</CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <ToolList tools={directDispatchTools} />
            </CardContent>
          </Card>
        </div>

        <Card className="border-slate-200 bg-white">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Database className="h-5 w-5 text-slate-600" />
              <CardTitle className="text-lg">代码来源</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
              <div className="rounded-md bg-slate-50 p-3">
                <Search className="mb-2 h-4 w-4 text-slate-500" />
                Supervisor 工具：<code>backend/app/services/supervisor/tools.py</code>
              </div>
              <div className="rounded-md bg-slate-50 p-3">
                <Search className="mb-2 h-4 w-4 text-slate-500" />
                子 Agent 工具：<code>outline_tools.py</code>、<code>chapter_tools.py</code>、<code>edit_chapter_tools.py</code>、<code>evaluation_tools.py</code>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
