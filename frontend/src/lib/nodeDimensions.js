/** 与 backend/canvas/app/constants.py 及 CustomNode 固定尺寸保持一致 */
export const NODE_WIDTH = 250;
export const NODE_HEIGHT = 120;
export const ELEMENT_SIZE = 90;

export function isElementNode(node) {
  return node?.data?.type === "element" || node?.type === "element";
}

export function getNodeDimensions(node) {
  if (isElementNode(node)) {
    return {
      width: node.measured?.width || node.width || ELEMENT_SIZE,
      height: node.measured?.height || node.height || ELEMENT_SIZE,
    };
  }
  return {
    width: node.measured?.width || node.width || NODE_WIDTH,
    height: node.measured?.height || node.height || NODE_HEIGHT,
  };
}

export function nodeBoundsFromFlowNode(node) {
  const { width, height } = getNodeDimensions(node);
  return {
    x: node.position.x,
    y: node.position.y,
    width,
    height,
    right: node.position.x + width,
    bottom: node.position.y + height,
  };
}

/** 节点外边界上的连接锚点（四边中点） */
export function anchorOnOuterBoundary(bounds, side) {
  const cx = bounds.x + bounds.width / 2;
  const cy = bounds.y + bounds.height / 2;
  if (side === "top") return { x: cx, y: bounds.y };
  if (side === "right") return { x: bounds.right, y: cy };
  if (side === "left") return { x: bounds.x, y: cy };
  return { x: cx, y: bounds.bottom };
}

/** Handle 落在外边界上（相对节点容器） */
export const BOUNDARY_HANDLE_STYLES = {
  top: { left: "50%", top: 0, transform: "translate(-50%, -50%)" },
  right: { top: "50%", right: 0, transform: "translate(50%, -50%)" },
  bottom: { left: "50%", bottom: 0, transform: "translate(-50%, 50%)" },
  left: { top: "50%", left: 0, transform: "translate(-50%, -50%)" },
};

export function flowNodeDimensionsFromRaw(rawNode) {
  if (rawNode.type === "element") {
    return { width: ELEMENT_SIZE, height: ELEMENT_SIZE };
  }
  return { width: NODE_WIDTH, height: NODE_HEIGHT };
}
