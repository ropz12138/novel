import { useState, useCallback, useEffect } from "react";
import { EdgeLabelRenderer, getBezierPath } from "@xyflow/react";

const MAX_LABEL_LENGTH = 18;

/** 角色关系线 — 与画布结构关联线视觉区分 */
export default function CharacterRelationEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  label,
  markerEnd,
  selected,
  data = {},
}) {
  const [isHovered, setIsHovered] = useState(false);

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const relationType = data.relation_type || label || "关系";
  const displayText = data.label
    ? `${relationType} · ${data.label}`
    : relationType;
  const shouldTruncate = displayText.length > MAX_LABEL_LENGTH;
  const shown = shouldTruncate && !isHovered
    ? displayText.substring(0, MAX_LABEL_LENGTH) + "..."
    : displayText;

  const baseStyle = {
    stroke: "#db2777",
    strokeWidth: 2,
    strokeDasharray: "6,4",
    ...style,
  };

  return (
    <>
      <path
        id={id}
        style={{ ...baseStyle, transition: "stroke 0.3s", fill: "none" }}
        className={`react-flow__edge-path ${selected ? "!stroke-rose-600" : ""}`}
        d={edgePath}
        markerEnd={markerEnd}
        fill="none"
      />
      <path
        className="edge-hit-area character-relation-hit"
        style={{ ...baseStyle, strokeWidth: 12, stroke: "transparent", strokeOpacity: 0 }}
        d={edgePath}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        fill="none"
      />
      {shown && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
            className="nodrag nopan px-1.5 py-0.5 text-[10px] rounded bg-rose-50 text-rose-700 border border-rose-200 max-w-[140px] truncate"
            title={displayText}
          >
            {shown}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
