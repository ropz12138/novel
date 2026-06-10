import { useEffect, useState } from "react";
import { BookOpen, Bot, LayoutList } from "lucide-react";
import { cn } from "../lib/utils";

export function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
    const update = () => setIsMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [breakpoint]);

  return isMobile;
}

export function resolveMobilePanelFromRoute(mainTab, chatOpen) {
  if (chatOpen) return "chat";
  return mainTab === "outline" ? "outline" : "detail";
}

export function shouldShowMobilePanel(isMobile, mobilePanel, panelId) {
  return !isMobile || mobilePanel === panelId;
}

export function shouldShowWorkPanel(isMobile, mobilePanel, mainTab, panelId) {
  if (!isMobile) {
    if (panelId === "chat") return false;
    return panelId === "outline" ? mainTab === "outline" : mainTab === "chapter";
  }
  return mobilePanel === panelId;
}

/** 手机端禁用大纲树 ↔ 网状图节点联动跳转 */
export function shouldSyncOutlineNodeSelection(isMobile) {
  return !isMobile;
}

/** 手机端角色卡单列全宽，桌面端多列网格 */
export function characterCardsGridClassName(isMobile) {
  if (isMobile) {
    return "grid min-w-0 grid-cols-1 gap-2";
  }
  return "grid min-w-0 gap-2 md:grid-cols-2 xl:grid-cols-3";
}

export function resolveDefaultChapterNum(filledChapterNums = [], chapterNumbers = []) {
  const numericFilled = filledChapterNums
    .map((n) => Number(n))
    .filter((n) => Number.isFinite(n));
  if (numericFilled.length > 0) {
    return Math.max(...numericFilled);
  }

  const numericOutline = chapterNumbers
    .map((n) => Number(n))
    .filter((n) => Number.isFinite(n));
  if (numericOutline.length > 0) {
    return Math.max(...numericOutline);
  }

  return null;
}

export function MobileWorkNav({ panel, onOutline, onDetail, onChat }) {
  const tabs = [
    { id: "outline", label: "大纲", icon: LayoutList, onClick: onOutline },
    { id: "detail", label: "正文", icon: BookOpen, onClick: onDetail },
    { id: "chat", label: "对话", icon: Bot, onClick: onChat },
  ];

  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 shadow-[0_-4px_24px_rgba(15,23,42,0.06)] backdrop-blur-md md:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      aria-label="作品详情导航"
    >
      <div className="grid grid-cols-3 gap-1 px-2 pt-1.5 pb-2">
        {tabs.map(({ id, label, icon: Icon, onClick }) => {
          const active = panel === id;
          return (
            <button
              key={id}
              type="button"
              onClick={onClick}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 rounded-xl py-2 text-[11px] font-medium transition-colors",
                active ? "bg-blue-50 text-blue-700" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800",
              )}
            >
              <Icon className={cn("h-5 w-5", active && "text-blue-600")} />
              {label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

export function MobileChapterStrip({ chapters, activeNum, onSelect }) {
  if (!chapters.length) return null;

  return (
    <div className="mb-3 flex gap-2 overflow-x-auto pb-1 md:hidden" role="tablist" aria-label="章节列表">
      {chapters.map((ch) => {
        const num = ch.chapter_number;
        const active = num === activeNum;
        return (
          <button
            key={num}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(num)}
            className={cn(
              "shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              active ? "bg-blue-600 text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:bg-slate-200",
            )}
          >
            {ch.title ? `第${num}章 · ${ch.title}` : `第${num}章`}
          </button>
        );
      })}
    </div>
  );
}
