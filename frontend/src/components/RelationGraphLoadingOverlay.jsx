import { Loader2 } from "lucide-react";
import { getRelationGraphLoadingMessage } from "../lib/relationGraphLoading";

/**
 * @param {{ phase?: import("../lib/relationGraphLoading").RelationGraphLoadingPhase | string }} props
 */
export function RelationGraphLoadingOverlay({ phase }) {
  const message = getRelationGraphLoadingMessage(phase);

  return (
    <div
      className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-slate-50/92 backdrop-blur-[2px]"
      aria-busy="true"
      aria-live="polite"
      role="status"
    >
      <div className="relation-graph-loading-mesh" aria-hidden="true">
        <span className="relation-graph-loading-mesh__node relation-graph-loading-mesh__node--a" />
        <span className="relation-graph-loading-mesh__node relation-graph-loading-mesh__node--b" />
        <span className="relation-graph-loading-mesh__node relation-graph-loading-mesh__node--c" />
        <span className="relation-graph-loading-mesh__node relation-graph-loading-mesh__node--d" />
        <span className="relation-graph-loading-mesh__node relation-graph-loading-mesh__node--e" />
        <span className="relation-graph-loading-mesh__edge relation-graph-loading-mesh__edge--ab" />
        <span className="relation-graph-loading-mesh__edge relation-graph-loading-mesh__edge--ac" />
        <span className="relation-graph-loading-mesh__edge relation-graph-loading-mesh__edge--bd" />
        <span className="relation-graph-loading-mesh__edge relation-graph-loading-mesh__edge--ce" />
        <span className="relation-graph-loading-mesh__edge relation-graph-loading-mesh__edge--de" />
      </div>
      <Loader2 className="mt-5 h-6 w-6 animate-spin text-violet-500" />
      <p className="mt-3 text-sm font-medium text-slate-700">{message}</p>
      <p className="mt-1 text-xs text-slate-500">节点较多时布局计算可能需要数秒</p>
    </div>
  );
}
