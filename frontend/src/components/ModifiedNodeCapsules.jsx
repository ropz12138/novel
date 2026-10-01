export default function ModifiedNodeCapsules({ nodes = [], onRemove }) {
  if (!nodes.length) return null;
  return (
    <div aria-label="待发送的节点修改" className="pointer-events-auto mb-2 flex flex-wrap gap-1">
      {nodes.map((node) => (
        <span key={node.id} className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2 py-1 text-xs text-blue-800">
          已修改：{node.label}
          <button type="button" aria-label={`移除修改记录 ${node.label}`} onClick={() => onRemove(node.id)}>×</button>
        </span>
      ))}
    </div>
  );
}
