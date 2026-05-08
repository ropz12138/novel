import { useState } from "react";
import { Check, MessageSquare, X } from "lucide-react";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";

export function ConfirmBar({ type, onConfirm, onReject, onGuide, loading = false }) {
  const [showGuide, setShowGuide] = useState(false);
  const [guideText, setGuideText] = useState("");

  const handleGuide = () => {
    if (guideText.trim()) {
      onGuide(guideText.trim());
      setGuideText("");
      setShowGuide(false);
    }
  };

  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={onConfirm}
          disabled={loading}
          className="h-7 text-xs"
        >
          <Check className="mr-1 h-3 w-3" />
          确认
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onReject}
          disabled={loading}
          className="h-7 text-xs"
        >
          <X className="mr-1 h-3 w-3" />
          拒绝
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowGuide(!showGuide)}
          disabled={loading}
          className="h-7 text-xs"
        >
          <MessageSquare className="mr-1 h-3 w-3" />
          给指导意见
        </Button>
      </div>

      {showGuide && (
        <div className="flex gap-2">
          <Textarea
            value={guideText}
            onChange={(e) => setGuideText(e.target.value)}
            placeholder="输入你的指导意见..."
            className="min-h-[60px] text-xs"
            rows={2}
          />
          <Button
            size="sm"
            onClick={handleGuide}
            disabled={!guideText.trim() || loading}
            className="h-auto shrink-0 text-xs"
          >
            发送
          </Button>
        </div>
      )}
    </div>
  );
}
