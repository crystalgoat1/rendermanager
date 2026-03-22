import { createContext } from "preact";
import { useState, useEffect, useCallback, useRef, useContext } from "preact/hooks";
import type { ComponentChildren } from "preact";

interface InfoTooltipContextValue {
  activeId: string | null;
  open: (id: string) => void;
  close: (id: string) => void;
}

export const InfoTooltipCtx = createContext<InfoTooltipContextValue>({
  activeId: null,
  open: () => {},
  close: () => {},
});

export function InfoTooltipProvider({ children }: { children: ComponentChildren }) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const scrollFrameRef = useRef(0);

  const open = useCallback((id: string) => setActiveId(id), []);
  const close = useCallback(
    (id: string) => setActiveId((prev) => (prev === id ? null : prev)),
    [],
  );

  // Dismiss on any scroll (captures scrolling on any element)
  useEffect(() => {
    if (!activeId) return;

    const handleScroll = () => {
      // Debounce with rAF so we don't fire dozens of times
      cancelAnimationFrame(scrollFrameRef.current);
      scrollFrameRef.current = requestAnimationFrame(() => setActiveId(null));
    };

    // Use capture so we catch scroll on any nested element (not just window)
    window.addEventListener("scroll", handleScroll, { capture: true, passive: true });
    return () => {
      cancelAnimationFrame(scrollFrameRef.current);
      window.removeEventListener("scroll", handleScroll, { capture: true });
    };
  }, [activeId]);

  return (
    <InfoTooltipCtx.Provider value={{ activeId, open, close }}>
      {children}
    </InfoTooltipCtx.Provider>
  );
}

export function useInfoTooltip() {
  return useContext(InfoTooltipCtx);
}
