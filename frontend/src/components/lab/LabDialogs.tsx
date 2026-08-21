import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { GitCompare } from "lucide-react"
import { lab } from "@/lib/api"
import type { LabKeyframe, LabSegment, LabVideo } from "@/lib/types"
import { ProviderSelect } from "@/components/lab/ProviderSelect"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

export function CompareBody({ exclude, busy, onSubmit }: { exclude: string | null; busy: boolean; onSubmit: (p: string) => void }) {
  const [p, setP] = useState("")
  return (
    <div className="space-y-3">
      <ProviderSelect value={p} onChange={setP} exclude={exclude} />
      <div className="flex justify-end"><Button disabled={!p || busy} onClick={() => onSubmit(p)}><GitCompare className="size-4" /> Clone & render</Button></div>
    </div>
  )
}

export function EditSegmentDialog({ seg, supportsEdit, onClose, onSubmit, busy }: { seg: LabSegment | null; supportsEdit: boolean; onClose: () => void; busy: boolean
  onSubmit: (index: number, body: { prompt?: string | null; edit_instruction?: string | null }) => void }) {
  const [mode, setMode] = useState<"motion" | "edit">("motion")
  const [p, setP] = useState("")
  const [instr, setInstr] = useState("")
  const cur = seg ? (p || seg.prompt || "") : ""
  const canEdit = supportsEdit && !!seg?.editable && !!seg?.video_url
  return (
    <Dialog open={!!seg} onOpenChange={o => { if (!o) { setP(""); setInstr(""); setMode("motion"); onClose() } }}>
      <DialogContent className="sm:max-w-3xl">
        {seg && (<>
          <DialogHeader>
            <DialogTitle className="font-heading">Segment #{seg.index + 1} · frames {seg.from_index}→{seg.to_index} — edit & redo</DialogTitle>
            <DialogDescription>Only this clip is regenerated; the final video is rebuilt automatically afterwards.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 md:grid-cols-[220px_1fr]">
            <div className="aspect-[9/16] overflow-hidden rounded bg-black">
              {seg.video_url ? <video src={`/api${seg.video_url}`} controls muted playsInline className="h-full w-full" /> : <div className="grid h-full place-items-center text-xs text-muted-foreground">no clip yet</div>}
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex gap-1 rounded-md border border-border p-1">
                <button type="button" onClick={() => setMode("motion")} className={cn("flex-1 rounded px-2 py-1.5 text-xs", mode === "motion" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>Re-animate with a new motion prompt</button>
                <button type="button" disabled={!canEdit} title={canEdit ? "" : "Conversational editing is available for clips generated with Gemini Omni"} onClick={() => setMode("edit")}
                  className={cn("flex-1 rounded px-2 py-1.5 text-xs disabled:opacity-40", mode === "edit" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>Edit the existing clip (Omni)</button>
              </div>
              {mode === "motion" ? (<>
                <Textarea rows={6} value={cur} onChange={e => setP(e.target.value)} placeholder="Slow push in; she opens the laptop and starts typing…" />
                <p className="text-[11px] text-muted-foreground">Generated again from keyframe {seg.from_index} (start) and keyframe {seg.to_index} (end reference) with this motion description.</p>
              </>) : (<>
                <Textarea rows={6} value={instr} onChange={e => setInstr(e.target.value)} placeholder="Make the lighting more dramatic. Keep everything else the same." />
                <p className="text-[11px] text-muted-foreground">Conversational edit of this exact clip. Simple instructions work best; add “Keep everything else the same” to preserve the rest.</p>
              </>)}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => { setP(""); setInstr(""); onClose() }}>Cancel</Button>
                <Button disabled={busy || (mode === "motion" ? cur.trim().length < 5 : instr.trim().length < 3)}
                  onClick={() => onSubmit(seg.index, mode === "motion" ? { prompt: cur.trim() } : { edit_instruction: instr.trim() })}>
                  {mode === "motion" ? "Re-animate segment" : "Apply edit"}
                </Button>
              </div>
            </div>
          </div>
        </>)}
      </DialogContent>
    </Dialog>
  )
}

export function ChangeLengthDialog({ open, video, onClose, onSubmit, busy }: { open: boolean; video: LabVideo; onClose: () => void; onSubmit: (d: number) => void; busy: boolean }) {
  const [d, setD] = useState(video.target_duration)
  const { data: est } = useQuery({ queryKey: ["lab-estimate", video.video_provider, d], queryFn: () => lab.estimate(video.video_provider ?? "omni", d), placeholderData: prev => prev })
  const segs = est?.n_segments ?? video.n_segments, segLen = est?.segment_seconds ?? video.segment_seconds
  const sameCount = segs === video.n_segments
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading">Change video length</DialogTitle>
          <DialogDescription>Current: {video.target_duration}s · {video.n_segments} × {video.segment_seconds}s</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <div className="mb-1 flex justify-between text-xs"><span className="uppercase tracking-wider text-muted-foreground">New length</span><span className="font-mono">{d}s</span></div>
            <input type="range" min={3} max={25} step={1} value={d} onChange={e => setD(Number(e.target.value))} className="scrub w-full" />
            <div className="mt-1 font-mono text-[11px] text-muted-foreground">{segs + 1} keyframes · {segs} × {segLen}s clips{est ? ` · ≈ $${est.total.toFixed(2)}` : ""}</div>
          </div>
          <p className={cn("rounded-md border p-3 text-xs", sameCount ? "border-border text-muted-foreground" : "border-primary/40 bg-primary/5 text-foreground")}>
            {sameCount ? "Segment count stays the same: your keyframes are kept and the clips are re-animated with the new length."
              : "Segment count changes: the storyboard is re-planned and all keyframes are regenerated (you'll review them again before animating)."}
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button disabled={busy || d === video.target_duration} onClick={() => onSubmit(d)}>{sameCount ? "Apply & re-animate" : "Apply & re-plan"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function EditKeyframeDialog({ kf, video, onClose, onSubmit, busy }: { kf: LabKeyframe | null; video: LabVideo; onClose: () => void; onSubmit: (i: number, p: string) => void; busy: boolean }) {
  const [p, setP] = useState("")
  const cur = kf ? (p || kf.prompt) : ""
  return (
    <Dialog open={!!kf} onOpenChange={o => { if (!o) { setP(""); onClose() } }}>
      <DialogContent className="sm:max-w-3xl">
        {kf && (<>
          <DialogHeader><DialogTitle className="font-heading">Keyframe {kf.index === 0 ? "START" : kf.index === video.n_segments ? "END" : `#${kf.index}`} — edit prompt & regenerate</DialogTitle></DialogHeader>
          <div className="grid gap-4 md:grid-cols-[220px_1fr]">
            <div className="aspect-[9/16] overflow-hidden rounded bg-surface-2">{kf.image_url && <img src={`/api${kf.image_url}`} alt="" className="h-full w-full object-cover" />}</div>
            <div className="space-y-3">
              <Textarea rows={8} value={cur} onChange={e => setP(e.target.value)} />
              <p className="text-[11px] text-muted-foreground">The style guide is appended automatically so the frame stays consistent with the others. Segments touching this frame will be re-animated.</p>
              <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => { setP(""); onClose() }}>Cancel</Button><Button disabled={busy || cur.trim().length < 5} onClick={() => onSubmit(kf.index, cur.trim())}>Regenerate image</Button></div>
            </div>
          </div>
        </>)}
      </DialogContent>
    </Dialog>
  )
}
