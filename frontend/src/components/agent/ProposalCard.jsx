import { GitBranch } from "lucide-react";

export function ProposalCard({ reason, operations }) {
  if (!operations || operations.length === 0) return null;

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
      <div className="mb-2 flex items-center gap-2">
        <GitBranch className="h-4 w-4 text-amber-600" />
        <span className="text-xs font-medium text-amber-700">大纲修改建议</span>
      </div>

      {reason && (
        <p className="mb-2 text-xs text-amber-800">{reason}</p>
      )}

      <div className="space-y-1.5">
        {operations.map((op, idx) => (
          <div key={idx} className="rounded bg-white/70 px-2.5 py-1.5 text-xs text-slate-600">
            <span className="font-mono font-medium text-amber-700">{op.tool}</span>
            {op.args && (
              <span className="ml-2 text-slate-500">
                {Object.entries(op.args).map(([k, v]) => (
                  <span key={k} className="mr-2">
                    <span className="text-slate-400">{k}:</span> {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </span>
                ))}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
