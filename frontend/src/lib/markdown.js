export function remarkHtmlBreaks() {
  return (tree) => {
    const visit = (node) => {
      if (!Array.isArray(node?.children)) return;
      node.children = node.children.map((child) => {
        if (child?.type === "html" && /^<br\s*\/?\s*>$/i.test(child.value.trim())) {
          return { type: "break" };
        }
        visit(child);
        return child;
      });
    };
    visit(tree);
  };
}
