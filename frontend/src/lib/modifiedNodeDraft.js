export function attachModifiedNodes(message, nodes, sessionId) {
  if (!sessionId || !nodes.length) return message;
  return nodes.map((node) => `[[ctx|${node.id}|${node.type}|已修改：${node.label}]]`).join("\n") + "\n" + message;
}
