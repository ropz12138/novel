import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getTtsSettings, putTtsSettings } from "../lib/ttsApi";

export default function TtsConfigDialog({ open, onClose }) {
  const [style, setStyle] = useState("");
  const [description, setDescription] = useState("");
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setReady(false);
    setError("");
    getTtsSettings().then((data) => {
      if (cancelled) return;
      setStyle(data.mimo_tts.style);
      setDescription(data.mimo_voicedesign.voice_description);
      setReady(true);
    }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [open]);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await putTtsSettings({
        mimo_tts: { style },
        mimo_voicedesign: { voice_description: description },
      });
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => { if (!saving) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="tts-settings-title"
        className="max-h-[85dvh] w-full max-w-xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 id="tts-settings-title" className="text-lg font-semibold text-slate-800">朗读设置</h2>
          <button aria-label="关闭朗读设置" disabled={saving} onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100">
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="mb-4 text-sm text-gray-500">设置对所有用户生效。保存后用于新发起的朗读请求，已预取的音频保持原样。</p>
        {!ready && !error && <p className="py-6 text-center text-sm text-gray-500">加载中...</p>}
        {ready && <div className="space-y-4">
          <div>
            <label htmlFor="tts-style" className="mb-1 block text-sm font-medium text-slate-700">普通 TTS 朗读风格</label>
            <p className="mb-2 text-xs text-gray-500">描述语气、情绪和语速；留空则由模型自行演绎。</p>
            <textarea id="tts-style" rows={5} value={style} disabled={saving} onChange={(e) => setStyle(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
          </div>
          <div>
            <label htmlFor="tts-description" className="mb-1 block text-sm font-medium text-slate-700">VoiceDesign 音色描述</label>
            <p className="mb-2 text-xs text-gray-500">描述声音的年龄、音质、口音和演绎方式。</p>
            <textarea id="tts-description" rows={6} value={description} disabled={saving} onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
          </div>
        </div>}
        {error && <p role="alert" className="mt-3 text-sm text-red-500">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button disabled={saving} onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100">取消</button>
          <button disabled={!ready || saving || !description.trim()} onClick={save}
            className="rounded-lg bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50">
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
