import { useEffect, useLayoutEffect, useRef, useState } from "react";
import "./WorkbenchSidebar.css";

const MIN_WIDTH = 200;
const MAX_WIDTH = 520;
const RAIL_WIDTH = 40;
const KEYBOARD_STEP = 20;
const MOBILE_QUERY = "(max-width: 800px)";

function clampWidth(value) {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(value)));
}

export function WorkbenchSidebar({
  side,
  title,
  icon,
  collapsed,
  onCollapsedChange,
  width,
  onWidthChange,
  children,
  headerExtra,
  className,
}) {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches);
  const dragRef = useRef(null);
  const desktopCollapsed = !mobile && collapsed;
  const clampedWidth = clampWidth(width);
  const style = mobile
    ? { width: "100%", flexBasis: "100%", flexGrow: 1, flexShrink: 1, minWidth: 0 }
    : desktopCollapsed
      ? { width: `${RAIL_WIDTH}px`, flexBasis: `${RAIL_WIDTH}px`, flexGrow: 0, flexShrink: 0, minWidth: 0 }
      : { width: `${clampedWidth}px`, flexBasis: `${clampedWidth}px`, flexGrow: 0, flexShrink: 1, minWidth: 0 };

  useEffect(() => {
    const media = window.matchMedia(MOBILE_QUERY);
    const onChange = () => setMobile(media.matches);
    media.addEventListener("change", onChange);
    setMobile(media.matches);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useLayoutEffect(() => () => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    drag.node.releasePointerCapture(drag.pointerId);
  }, []);

  function onPointerDown(event) {
    if (event.button !== 0) return;
    const node = event.currentTarget;
    node.setPointerCapture(event.pointerId);
    dragRef.current = {
      node,
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: clampedWidth,
    };
  }

  function onPointerMove(event) {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const delta = side === "left" ? event.clientX - drag.startX : drag.startX - event.clientX;
    onWidthChange(clampWidth(drag.startWidth + delta));
  }

  function endPointer(event) {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    dragRef.current = null;
    drag.node.releasePointerCapture(drag.pointerId);
  }

  function onKeyDown(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const towardEnd = event.key === "ArrowRight" ? 1 : -1;
    const signed = side === "left" ? towardEnd : -towardEnd;
    onWidthChange(clampWidth(clampedWidth + signed * KEYBOARD_STEP));
  }

  const toggleLabel = collapsed ? `展开${title}` : `收起${title}`;
  const toggleGlyph = side === "left"
    ? (collapsed ? "›" : "‹")
    : (collapsed ? "‹" : "›");

  return (
    <aside
      className={[
        "workbench-sidebar",
        `workbench-sidebar--${side}`,
        mobile ? "is-mobile" : "",
        desktopCollapsed ? "is-collapsed" : "",
        className,
      ].filter(Boolean).join(" ")}
      style={style}
      data-side={side}
      aria-label={title}
    >
      <div className="workbench-sidebar__header">
        {icon ? <span className="workbench-sidebar__icon">{icon}</span> : null}
        <span className="workbench-sidebar__title">{title}</span>
        {headerExtra ? <div className="workbench-sidebar__extra">{headerExtra}</div> : null}
        {mobile ? null : (
          <button
            type="button"
            className="workbench-sidebar__toggle"
            aria-expanded={!collapsed}
            aria-label={toggleLabel}
            title={toggleLabel}
            onClick={() => onCollapsedChange(!collapsed)}
          >
            <span aria-hidden="true">{toggleGlyph}</span>
          </button>
        )}
      </div>
      {mobile || collapsed ? null : (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={`调整${title}宽度`}
          aria-valuemin={MIN_WIDTH}
          aria-valuemax={MAX_WIDTH}
          aria-valuenow={clampedWidth}
          tabIndex={0}
          className="workbench-sidebar__separator"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endPointer}
          onPointerCancel={endPointer}
          onKeyDown={onKeyDown}
        />
      )}
      <div className="workbench-sidebar__body" hidden={desktopCollapsed}>
        {children}
      </div>
    </aside>
  );
}
