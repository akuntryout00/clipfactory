import { useCallback, useEffect, useRef, useState } from "react"
import { Play, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/**
 * Usable-range trimmer: a video preview with two draggable handles on a scrub bar.
 * Dragging a handle seeks the video to that frame; "Set start/end here" uses the current playhead;
 * "Preview range" plays only the selected segment.
 */
export function RangeTrimmer({ src, duration, start, end, onChange, className }: {
  src: string; duration: number; start: number; end: number; onChange: (s: number, e: number) => void; className?: string
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const [t, setT] = useState(0)
  const [dur, setDur] = useState(duration || 0)
  const [previewing, setPreviewing] = useState(false)
  const dragging = useRef<"start" | "end" | null>(null)
  const total = dur || duration || 1
  const pct = (v: number) => `${Math.min(100, Math.max(0, (v / total) * 100))}%`
  const clamp = (v: number) => Math.min(total, Math.max(0, v))
  const seek = useCallback((v: number) => { const el = videoRef.current; if (el) { el.currentTime = v; setT(v) } }, [])

  const posToTime = (clientX: number) => {
    const r = barRef.current!.getBoundingClientRect()
    return clamp(((clientX - r.left) / r.width) * total)
  }
  const onPointerMove = useCallback((e: PointerEvent) => {
    if (!dragging.current) return
    const v = Math.round(posToTime(e.clientX) * 20) / 20
    if (dragging.current === "start") { const s = Math.min(v, end - 0.1); onChange(s, end); seek(s) }
    else { const en = Math.max(v, start + 0.1); onChange(start, en); seek(en) }
  }, [start, end, total, onChange, seek]) // eslint-disable-line react-hooks/exhaustive-deps
  const stopDrag = useCallback(() => { dragging.current = null }, [])
  useEffect(() => {
    window.addEventListener("pointermove", onPointerMove)
    window.addEventListener("pointerup", stopDrag)
    return () => { window.removeEventListener("pointermove", onPointerMove); window.removeEventListener("pointerup", stopDrag) }
  }, [onPointerMove, stopDrag])

  // preview: play from start, stop at end
  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    const tick = () => {
      setT(el.currentTime)
      if (previewing && el.currentTime >= end - 0.02) { el.pause(); setPreviewing(false) }
    }
    el.addEventListener("timeupdate", tick)
    return () => el.removeEventListener("timeupdate", tick)
  }, [previewing, end])
  const preview = () => {
    const el = videoRef.current
    if (!el) return
    if (previewing) { el.pause(); setPreviewing(false); return }
    el.currentTime = start; el.muted = true; setPreviewing(true); void el.play()
  }

  const fmt = (v: number) => `${v.toFixed(2)}s`
  return (
    <div className={cn("space-y-2", className)}>
      <video ref={videoRef} src={src} muted playsInline preload="metadata" className="aspect-[9/16] w-full rounded-md bg-black"
        onLoadedMetadata={e => { if (!duration) setDur(e.currentTarget.duration) }}
        onClick={e => { const el = e.currentTarget; if (el.paused) void el.play(); else el.pause() }} />
      {/* scrub bar with range */}
      <div ref={barRef} className="relative h-8 select-none touch-none rounded-md bg-surface-2"
        onPointerDown={e => { if ((e.target as HTMLElement).dataset.handle) return; seek(posToTime(e.clientX)) }}>
        <div className="absolute inset-y-0 rounded-md bg-primary/25" style={{ left: pct(start), width: pct(end - start) }} />
        <div className="pointer-events-none absolute inset-y-0 w-px bg-foreground" style={{ left: pct(t) }} />
        {(["start", "end"] as const).map(h => (
          <div key={h} data-handle={h} role="slider" aria-label={`usable ${h}`} aria-valuenow={h === "start" ? start : end} aria-valuemin={0} aria-valuemax={total}
            tabIndex={0}
            onPointerDown={e => { e.preventDefault(); dragging.current = h; seek(h === "start" ? start : end) }}
            onKeyDown={e => {
              const step = e.shiftKey ? 0.5 : 0.05
              const d = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0
              if (!d) return
              e.preventDefault()
              if (h === "start") { const s = clamp(Math.min(start + d, end - 0.1)); onChange(s, end); seek(s) }
              else { const en = clamp(Math.max(end + d, start + 0.1)); onChange(start, en); seek(en) }
            }}
            style={{ left: pct(h === "start" ? start : end) }}
            className={cn("absolute top-0 h-full w-3 -translate-x-1/2 cursor-ew-resize rounded-sm bg-primary shadow focus-visible:outline-2 focus-visible:outline-ring",
              h === "start" ? "rounded-r-none" : "rounded-l-none")}>
            <span className="absolute -bottom-4 left-1/2 -translate-x-1/2 font-mono text-[10px] text-primary">{h === "start" ? start.toFixed(1) : end.toFixed(1)}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 pt-3">
        <Button type="button" size="sm" variant="outline" onClick={() => { const s = clamp(Math.min(t, end - 0.1)); onChange(Math.round(s * 20) / 20, end) }}>Set start here</Button>
        <Button type="button" size="sm" variant="outline" onClick={() => { const en = clamp(Math.max(t, start + 0.1)); onChange(start, Math.round(en * 20) / 20) }}>Set end here</Button>
        <Button type="button" size="sm" variant={previewing ? "default" : "outline"} onClick={preview}>
          {previewing ? <Square className="size-3.5" /> : <Play className="size-3.5" />} {previewing ? "Stop" : "Preview range"}
        </Button>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{fmt(start)} → {fmt(end)} · {fmt(end - start)} usable · playhead {fmt(t)}</span>
      </div>
    </div>
  )
}
