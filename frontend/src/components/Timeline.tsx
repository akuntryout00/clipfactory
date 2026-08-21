import { useMemo } from "react"
import { media } from "@/lib/api"
import type { Plan } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * The Video JSON drawn as a real timeline: scene width = duration, thumbnails from the chosen B-roll,
 * overlay markers above, caption chunks below, playhead synced with the player.
 */
export function Timeline({ plan, currentTime, onSeek, onSceneClick, selectedScene }: {
  plan: Plan; currentTime: number; onSeek?: (t: number) => void; onSceneClick?: (order: number) => void; selectedScene?: number | null
}) {
  const total = plan.scenes[plan.scenes.length - 1]?.end ?? plan.voiceover.duration
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / total) * 100))}%`
  const ticks = useMemo(() => Array.from({ length: Math.floor(total) + 1 }, (_, i) => i), [total])
  return (
    <div className="select-none">
      {/* overlays */}
      <div className="relative h-5">
        {plan.scenes.filter(s => s.text).map(s => (
          <div key={s.order} style={{ left: pct(s.start), width: pct(s.end - s.start) }}
            className="absolute top-0 truncate rounded-sm border border-primary/50 bg-primary/10 px-1 font-mono text-[10px] leading-5 text-primary" title={s.text ?? ""}>
            {s.text}
          </div>
        ))}
      </div>
      {/* scenes */}
      <div className="relative mt-1 h-[92px] overflow-hidden rounded-md border border-border bg-surface-2"
        onClick={e => { if (!onSeek) return; const r = e.currentTarget.getBoundingClientRect(); onSeek(((e.clientX - r.left) / r.width) * total) }}>
        {plan.scenes.map(s => {
          const active = currentTime >= s.start && currentTime < s.end
          return (
            <button key={s.order} type="button" onClick={ev => { ev.stopPropagation(); onSceneClick?.(s.order); onSeek?.(s.start + 0.01) }}
              style={{ left: pct(s.start), width: pct(s.end - s.start) }}
              className={cn("group absolute top-0 h-full border-r border-background/80 text-left outline-none transition-[filter]",
                active ? "brightness-110" : "brightness-75 hover:brightness-100", selectedScene === s.order && "ring-2 ring-inset ring-primary")}>
              <img src={media.assetThumb(s.asset_id)} alt="" className="h-full w-full object-cover" loading="lazy" />
              <span className="absolute bottom-1 left-1 rounded bg-background/80 px-1 font-mono text-[10px] leading-4 text-foreground">
                {s.order} · {s.asset_id.replace("asset_", "#")}
              </span>
              <span className="absolute right-1 top-1 rounded bg-background/70 px-1 font-mono text-[10px] leading-4 text-muted-foreground">
                {(s.end - s.start).toFixed(1)}s
              </span>
            </button>
          )
        })}
        {/* playhead */}
        <div className="pointer-events-none absolute top-0 h-full w-px bg-primary shadow-[0_0_6px_#FFE500]" style={{ left: pct(currentTime) }} />
      </div>
      {/* captions */}
      <div className="relative mt-1 h-4">
        {plan.captions.map((c, i) => (
          <div key={i} style={{ left: pct(c.start), width: pct(Math.max(0.05, c.end - c.start)) }}
            className={cn("absolute top-1 h-2 rounded-sm border-r border-background", currentTime >= c.start && currentTime < c.end ? "bg-primary" : "bg-muted-foreground/40")}
            title={c.text} />
        ))}
      </div>
      {/* ruler */}
      <div className="relative mt-1 h-4 font-mono text-[10px] text-muted-foreground">
        {ticks.map(t => (
          <span key={t} style={{ left: pct(t) }} className="absolute -translate-x-1/2 border-l border-border pl-0.5 leading-4">{t % 2 === 0 ? `${t}s` : ""}</span>
        ))}
      </div>
    </div>
  )
}
