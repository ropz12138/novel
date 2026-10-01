import { useEffect, useRef, useState } from "react";
import { Capacitor, registerPlugin } from "@capacitor/core";


const NativeKeyboardInset = registerPlugin("KeyboardInset");


export function composerKeyboardOffset(innerHeight, visualViewport) {
  const covered = innerHeight - (visualViewport.offsetTop + visualViewport.height);
  return Math.max(0, Math.round(covered));
}


export function useKeyboardInset() {
  const [keyboardInset, setKeyboardInset] = useState(0);
  const stableHeightRef = useRef(0);

  useEffect(() => {
    if (Capacitor.isNativePlatform()) {
      let disposed = false;
      let listenerHandle;

      NativeKeyboardInset.addListener("keyboardInsetChanged", ({ height }) => {
        if (!disposed) setKeyboardInset(Math.max(0, Number(height) || 0));
      }).then((handle) => {
        if (disposed) handle.remove();
        else listenerHandle = handle;
      });
      NativeKeyboardInset.getInset().then(({ height }) => {
        if (!disposed) setKeyboardInset(Math.max(0, Number(height) || 0));
      });

      return () => {
        disposed = true;
        listenerHandle?.remove();
      };
    }

    const viewport = window.visualViewport;
    if (!viewport) return undefined;

    stableHeightRef.current = Math.max(
      stableHeightRef.current,
      window.innerHeight,
      viewport.offsetTop + viewport.height,
    );

    const update = () => {
      const visibleBottom = viewport.offsetTop + viewport.height;
      if (visibleBottom >= stableHeightRef.current) {
        stableHeightRef.current = visibleBottom;
      }
      setKeyboardInset(composerKeyboardOffset(stableHeightRef.current, viewport));
    };

    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    update();
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
    };
  }, []);

  return keyboardInset;
}
