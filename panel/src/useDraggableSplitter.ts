import { useCallback, useEffect, useState, type RefObject } from "react";

const HEIGHT_KEY = "aiwork.dockHeight";
const DEFAULT_HEIGHT = 300;

function readHeight(): number {
  const stored = localStorage.getItem(HEIGHT_KEY);
  if (stored == null) return DEFAULT_HEIGHT;
  const raw = Number(stored);
  if (!Number.isFinite(raw)) return DEFAULT_HEIGHT;
  return Math.min(640, Math.max(180, raw));
}

export function useDraggableSplitter(
  hostRef: RefObject<HTMLElement | null>,
  minHeight = 180,
) {
  const [bottomHeight, setBottomHeight] = useState(readHeight);
  const [isDragging, setIsDragging] = useState(false);

  const startDrag = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    setIsDragging(true);
  }, []);

  const resetHeight = useCallback(() => {
    setBottomHeight(DEFAULT_HEIGHT);
    localStorage.setItem(HEIGHT_KEY, String(DEFAULT_HEIGHT));
  }, []);

  useEffect(() => {
    if (!isDragging) return;

    const move = (event: MouseEvent) => {
      const host = hostRef.current;
      if (!host) return;
      const rect = host.getBoundingClientRect();
      const maxHeight = Math.max(minHeight, rect.height - 140);
      const next = rect.bottom - event.clientY;
      const clamped = Math.min(maxHeight, Math.max(minHeight, next));
      setBottomHeight(clamped);
      localStorage.setItem(HEIGHT_KEY, String(Math.round(clamped)));
    };

    const stop = () => setIsDragging(false);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
    };
  }, [hostRef, isDragging, minHeight]);

  return { bottomHeight, isDragging, startDrag, resetHeight };
}
