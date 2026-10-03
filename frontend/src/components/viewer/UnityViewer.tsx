"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Maximize2 } from "lucide-react";

import { API_BASE_URL } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/** Messages the Unity WebGL build posts to its parent window (see the Unity project's README). */
type ViewerMessage =
  | { type: "ready" }
  | { type: "progress"; value: number }
  | { type: "error"; message: string }
  | { type: "buildingSelected"; id: number; height_m: number }
  | { type: "picked"; u: number; v: number };

interface UnityInstance {
  SendMessage: (object: string, method: string, parameter: string) => void;
}

export interface UnityViewerHandle {
  /**
   * Send a scenario command (water, pin, explosion, fire, drop, landing, focus, pick, clear) to the viewer.
   * Commands sent before the scene has finished loading are held and delivered once it has.
   */
  run: (command: Record<string, unknown>) => void;
}

interface UnityViewerProps {
  /** The job to show. Render with `key={jobId}` so switching jobs remounts the viewer. */
  jobId: string;
  /** Extra classes for the iframe (height). */
  frameClassName?: string;
  /** Called with the load progress so a parent can show its own "loading" state. */
  onLoading?: (loading: boolean) => void;
  /** A terrain click made while a `pick` command was armed: fractions of the world width (east) and depth (north). */
  onPicked?: (u: number, v: number) => void;
}

export const UnityViewer = forwardRef<UnityViewerHandle, UnityViewerProps>(function UnityViewer({ jobId, frameClassName, onLoading, onPicked }, ref) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ id: number; heightM: number } | null>(null);
  const [src] = useState(() => `/unity/index.html?api=${encodeURIComponent(API_BASE_URL)}&job=${encodeURIComponent(jobId)}`);

  const loaded = useRef(false);
  const pending = useRef<{ name: string; json: string }[]>([]);
  const flushTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const onPickedRef = useRef(onPicked);
  useEffect(() => {
    onPickedRef.current = onPicked;
  }, [onPicked]);

  const flush = useCallback(() => {
    if (!loaded.current || pending.current.length === 0) return;
    const instance = (frameRef.current?.contentWindow as (Window & { unityInstance?: UnityInstance }) | null | undefined)?.unityInstance;
    if (!instance) {
      // the player is up but has not exposed its instance yet: try again shortly
      if (!flushTimer.current) {
        flushTimer.current = setInterval(() => {
          if (flushTimer.current) {
            clearInterval(flushTimer.current);
            flushTimer.current = null;
          }
          flush();
        }, 150);
      }
      return;
    }
    const queue = pending.current;
    pending.current = [];
    for (const item of queue) instance.SendMessage("ViewerBootstrap", "RunScenario", item.json);
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      run(command) {
        const name = String(command.cmd ?? "");
        // only the latest value of a continuously updated command matters
        if (name === "water" || name === "focus") pending.current = pending.current.filter((p) => p.name !== name);
        pending.current.push({ name, json: JSON.stringify(command) });
        flush();
      },
    }),
    [flush],
  );

  useEffect(() => {
    function onMessage(event: MessageEvent<ViewerMessage>) {
      // The build posts with target origin "*", so only trust our own iframe.
      if (event.source !== frameRef.current?.contentWindow || !event.data) return;
      const msg = event.data;
      if (msg.type === "progress") {
        setProgress(msg.value);
        if (msg.value >= 1) {
          loaded.current = true;
          flush();
        } else {
          loaded.current = false;
        }
      } else if (msg.type === "error") setError(msg.message);
      else if (msg.type === "buildingSelected") setSelected({ id: msg.id, heightM: msg.height_m });
      else if (msg.type === "picked") onPickedRef.current?.(msg.u, msg.v);
    }

    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      if (flushTimer.current) clearInterval(flushTimer.current);
    };
  }, [flush]);

  useEffect(() => {
    onLoading?.(progress > 0 && progress < 1);
  }, [progress, onLoading]);

  return (
    <div className="glass-panel rounded-2xl p-3">
      <div className="mb-2 flex items-center justify-between gap-3 px-2 text-xs text-muted-foreground">
        <span>
          Orbit: left-drag / wheel · Fly: press <kbd>C</kbd>, then WASD + mouse (Q/E down/up, Shift = fast)
        </span>
        <span className="flex items-center gap-3">
          {selected && (
            <span className="text-foreground">
              Building #{selected.id}: {selected.heightM.toFixed(1)} m
            </span>
          )}
          <button
            type="button"
            onClick={() => frameRef.current?.requestFullscreen?.()}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-white/10"
          >
            <Maximize2 className="size-3.5" /> Fullscreen
          </button>
        </span>
      </div>

      <iframe
        ref={frameRef}
        src={src}
        title="AakashDrishti 3D viewer"
        allow="fullscreen"
        className={cn("h-[70vh] min-h-[480px] w-full rounded-xl border border-white/10 bg-[#0b0e14]", frameClassName)}
      />

      {error ? (
        <p className="mt-2 whitespace-pre-wrap px-2 text-xs text-red-400">Viewer error: {error}</p>
      ) : progress > 0 && progress < 1 ? (
        <p className="mt-2 px-2 text-xs text-muted-foreground">Loading scene… {Math.round(progress * 100)}%</p>
      ) : null}
    </div>
  );
});
