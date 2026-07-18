import { useEffect, useState } from "react";
import { API_BASE } from "../../lib/runtime-config";

function getAuthHeaders() {
  const token = localStorage.getItem("novel_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function resolveIllustrationFetchUrl(src) {
  if (!src) return src;
  if (src.startsWith("http://") || src.startsWith("https://")) return src;
  if (src.startsWith("/api/")) {
    const root = API_BASE.replace(/\/api\/?$/, "");
    return `${root}${src}`;
  }
  return src;
}

export function isIllustrationApiPath(src) {
  return typeof src === "string" && /\/api\/illustrations\/[^/?#]+/.test(src);
}

export default function AuthIllustrationImage({ src, alt }) {
  const [blobUrl, setBlobUrl] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl = null;
    let cancelled = false;

    async function load() {
      if (!src) return;
      if (!isIllustrationApiPath(src)) {
        setBlobUrl(src);
        return;
      }

      try {
        const response = await fetch(resolveIllustrationFetchUrl(src), {
          headers: getAuthHeaders(),
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) {
          setBlobUrl(objectUrl);
          setFailed(false);
        }
      } catch {
        if (!cancelled) {
          setFailed(true);
          setBlobUrl(null);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [src]);

  if (failed) {
    return (
      <div className="my-4 rounded-lg border border-dashed border-gray-300 bg-gray-50 px-4 py-6 text-center text-sm text-gray-500">
        插图加载失败
      </div>
    );
  }

  if (!blobUrl) {
    return (
      <div className="my-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-400">
        插图加载中…
      </div>
    );
  }

  return (
    <img
      src={blobUrl}
      alt={alt || "章节插画"}
      className="my-4 w-full rounded-lg border border-gray-200 shadow-sm"
    />
  );
}
