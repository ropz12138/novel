export default function SessionContextUsage({ tokens }) {
  const value = Number.isFinite(Number(tokens)) ? Number(tokens) : 0;
  return (
    <span className="text-[10px] text-slate-400" title="最近一次已记录的模型请求输入 token 数，包含系统提示词、历史消息和工具结果；不是累计消耗。">
      【{value.toLocaleString("en-US")}】 tokens
    </span>
  );
}
