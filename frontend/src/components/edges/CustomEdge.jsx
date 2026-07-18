import { useState, useCallback, useEffect } from "react";
import { EdgeLabelRenderer, getBezierPath } from "@xyflow/react";

const MAX_LABEL_LENGTH = 18;

export default function CustomEdge({
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
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(false), 100);
    return () => clearTimeout(t);
  }, [flash]);

  const handleLabelClick = useCallback((e) => {
    e.stopPropagation();
    setFlash(true);
  }, []);

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const handleMouseEnter = useCallback(() => setIsHovered(true), []);
  const handleMouseLeave = useCallback(() => setIsHovered(false), []);

  const shouldTruncate = label && label.length > MAX_LABEL_LENGTH;
  const displayLabel = shouldTruncate && !isHovered
    ? label.substring(0, MAX_LABEL_LENGTH) + "..."
    : label;

  return (
    <>
      <path
        id={id}
        style={{ ...style, transition: "stroke 0.3s, opacity 0.3s", fill: "none" }}
        className={`react-flow__edge-path ${
          selected ? "stroke-blue-500" : ""
        } ${flash ? "!stroke-blue-500 !opacity-100" : ""}`}
        d={edgePath}
        markerEnd={markerEnd}
        fill="none"
      />
      {flash && (
        <path
          className="animate-pulse"
          style={{ ...style, stroke: "#3b82f6", strokeWidth: (style.strokeWidth || 1.5) + 3, opacity: 0.6 }}
          d={edgePath}
          markerEnd={markerEnd}
          fill="none"
        />
      )}
      <path
        className="edge-hit-area"
        style={{ ...style, strokeWidth: Math.max(style.strokeWidth || 1.5, 10), stroke: "transparent", strokeOpacity: 0 }}
        d={edgePath}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        fill="none"
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
              zIndex: isHovered ? 10000 : 1,
            }}
            className="nodrag nopan"
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            onClick={handleLabelClick}
          >
            <div
              className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-all duration-200 ${
                isHovered
                  ? "bg-white border border-gray-400 shadow-lg max-w-none"
                  : "bg-white/80 border border-gray-200 shadow-sm max-w-[180px]"
              }`}
              style={{ color: style.stroke || "#64748b" }}
            >
              <span className={isHovered ? "" : "truncate block"}>
                {displayLabel}
              </span>
            </div>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
