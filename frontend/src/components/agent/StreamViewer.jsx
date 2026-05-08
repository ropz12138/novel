import { useEffect, useRef } from "react";

export function StreamViewer({ text, isStreaming = false }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [text]);

  return (
    <div className="max-h-[400px] overflow-y-auto rounded-md bg-white/60 p-3 text-sm leading-relaxed text-slate-700">
      <pre className="whitespace-pre-wrap font-sans">{text}</pre>
      {isStreaming && (
        <span className="inline-block h-4 w-0.5 animate-pulse bg-blue-500 align-text-bottom" />
      )}
      <div ref={endRef} />
    </div>
  );
}
