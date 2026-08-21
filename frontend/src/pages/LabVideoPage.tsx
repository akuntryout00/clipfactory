import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, ArrowLeft, CheckCircle2, Clock, Download, Film, GitCompare, Loader2, RefreshCw, RotateCcw, Wand2 } from "lucide-react"
import { toast } from "sonner"
import { fmtDate, lab } from "@/lib/api"
import type { LabKeyframe, LabSegment, LabVideo } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { ProviderSelect } from "@/pages/LabPage"
import { Button, buttonVariants } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

const RUNNING = new Set(["PLANNING", "GENERATING_IMAGES", "ANIMATING"])
const STEPS = [
  { key: "describe", label: "1 · Describe" },
  { key: "plan", label: "2 · Storyboard (LLM)" },
  { key: "images", label: "3 · Keyframes (OpenAI)" },
  { key: "animate", label: "4 · Animate (Gemini Omni)" },
  { key: "done", label: "5 · Video" },
]
function stepIndex(v: LabVideo): number {
  if (v.status === "DONE") return 5
  if (v.status === "ANIMATING") return 3
  if (v.status === "IMAGES_READY") return 3
  if (v.status === "GENERATING_IMAGES") return 2
  if (v.status === "PLANNED") return 2
  if (v.status === "PLANNING") return 1
  if (v.status === "FAILED") { // where did it fail?
    if (!v.keyframes.length) return 1
    if (v.keyframes.some(k => k.status !== "DONE")) return 2
    return 3
  }
  return 1
}

export default function LabVideoPage() {
  const { id = "" } = useParams()
  const qc = useQueryClient()
  const { data: v, isLoading } = useQuery({ queryKey: ["lab", id], queryFn: () => lab.get(id), refetchInterval: q => (q.state.data && RUNNING.has(q.state.data.status) ? 2500 : false) })
  const [editing, setEditing] = useState<LabKeyframe | null>(null)
  const [editingSeg, setEditingSeg] = useState<LabSegment | null>(null)
  const [lengthOpen, setLengthOpen] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const nav = useNavigate()
  const cloneMut = useMutation({
    mutationFn: (provider: string) => lab.clone(id, { video_provider: provider, animate: true }),
    onSuccess: c => { toast.success(`Comparison started with ${c.provider_label ?? c.video_provider}`); setCompareOpen(false); qc.invalidateQueries({ queryKey: ["lab"] }); nav(`/lab/${c.id}`) },
    onError: e => toast.error(e.message),
  })
  const refresh = () => { qc.invalidateQueries({ queryKey: ["lab", id] }); qc.invalidateQueries({ queryKey: ["lab"] }) }
  const redoSeg = useMutation({
    mutationFn: ({ index, body }: { index: number; body: { prompt?: string | null; edit_instruction?: string | null } }) => lab.regenerateSegment(id, index, body),
    onSuccess: () => { toast.success("Redoing segment — the final video is rebuilt when it's done"); setEditingSeg(null); refresh() }, onError: e => toast.error(e.message),
  })
  const setLen = useMutation({
    mutationFn: (d: number) => lab.setDuration(id, d),
    onSuccess: v2 => { toast.success(v2.status === "PLANNING" ? "Length changed — re-planning storyboard and keyframes" : "Length changed — re-animating"); setLengthOpen(false); refresh() },
    onError: e => toast.error(e.message),
  })
  const gen = useMutation({ mutationFn: (onlyMissing: boolean) => lab.generateImages(id, onlyMissing), onSuccess: () => { toast.success("Generating keyframes"); refresh() }, onError: e => toast.error(e.message) })
  const regen = useMutation({ mutationFn: ({ index, prompt }: { index: number; prompt?: string | null }) => lab.regenerate(id, index, prompt), onSuccess: () => { toast.success("Regenerating keyframe"); setEditing(null); refresh() }, onError: e => toast.error(e.message) })
  const anim = useMutation({ mutationFn: (force: boolean) => lab.animate(id, force), onSuccess: () => { toast.success("Animating — this takes a few minutes"); refresh() }, onError: e => toast.error(e.message) })
  const retry = useMutation({ mutationFn: () => lab.retry(id), onSuccess: () => { toast.success("Retrying from the last incomplete step"); refresh() }, onError: e => toast.error(e.message) })
  if (isLoading || !v) return <div className="p-8 text-muted-foreground">Loading…</div>
  const running = RUNNING.has(v.status)
  const failed = v.status === "FAILED"
  const allImages = v.keyframes.length > 0 && v.keyframes.every(k => k.status === "DONE")
  const step = stepIndex(v)
  const doneKf = v.keyframes.filter(k => k.status === "DONE").length
  const doneSeg = v.segments.filter(s => s.status === "DONE").length
  const progress = v.status === "GENERATING_IMAGES" && v.keyframes.length ? doneKf / v.keyframes.length
    : v.status === "ANIMATING" && v.segments.length ? doneSeg / v.segments.length : null
  const title = v.prompt.length > 50 ? v.prompt.slice(0, 50).trimEnd() + "…" : v.prompt

  return (
    <div>
      <PageHeader eyebrow={<Link to="/lab" className="inline-flex items-center gap-1 hover:text-foreground"><ArrowLeft className="size-3" /> AI Lab</Link> as unknown as string}
        title={title}
        actions={<>
          {failed && <Button size="sm" onClick={() => retry.mutate()}><RotateCcw className="size-4" /> Retry</Button>}
          <Button variant="outline" size="sm" disabled={running} onClick={() => setLengthOpen(true)}><Clock className="size-4" /> Change length</Button>
          <Button variant="outline" size="sm" disabled={running} onClick={() => setCompareOpen(true)} title="Clone this storyboard and render it with another model"><GitCompare className="size-4" /> Compare with…</Button>
          <Button variant="outline" size="sm" disabled={running || !v.keyframes.length} onClick={() => gen.mutate(false)}><RefreshCw className="size-4" /> Regenerate all images</Button>
          <Button size="sm" disabled={running || !allImages} onClick={() => anim.mutate(v.status === "DONE")}><Film className="size-4" /> {v.status === "DONE" ? "Animate again" : "Animate video"}</Button>
        </>}>
        <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11px] text-muted-foreground">
          <span title={v.prompt} className="max-w-[60ch] truncate">{v.prompt}</span>
          <span>{v.id}</span><span>{v.target_duration}s target · {v.n_segments} × {v.segment_seconds}s</span>
          <span className="rounded border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-primary">{v.provider_label ?? v.video_provider} · {v.video_model}</span>
          <span>images {v.image_model}</span><span>{fmtDate(v.created_at)}</span>
        </div>
      </PageHeader>

      {/* status banner — always says what is happening right now */}
      <div className={cn("mx-8 mt-5 flex items-start gap-3 rounded-lg border p-4",
        failed ? "border-fail/50 bg-fail/10" : v.status === "DONE" ? "border-ready/40 bg-ready/10" : running ? "border-primary/50 bg-primary/5" : "border-border bg-card")}>
        {failed ? <AlertTriangle className="mt-0.5 size-5 shrink-0 text-fail" /> : v.status === "DONE" ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-ready" />
          : running ? <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-primary" /> : <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />}
        <div className="min-w-0 flex-1">
          <div className="font-heading text-sm font-semibold">
            {v.status === "PLANNING" && "Planning the storyboard…"}
            {v.status === "PLANNED" && "Storyboard ready — keyframes not generated yet"}
            {v.status === "GENERATING_IMAGES" && `Generating keyframe images · ${doneKf}/${v.keyframes.length} done`}
            {v.status === "IMAGES_READY" && "Keyframes ready — review them, then press “Animate video”"}
            {v.status === "ANIMATING" && `Animating segments · ${doneSeg}/${v.segments.length} done`}
            {v.status === "DONE" && `Video ready${v.final_duration ? ` · ${v.final_duration.toFixed(1)}s` : ""}`}
            {failed && "Something failed"}
          </div>
          <div className={cn("mt-0.5 text-xs", failed ? "text-fail" : "text-muted-foreground")}>{failed ? v.error : v.stage_message}</div>
          {progress != null && <div className="mt-2 h-1.5 overflow-hidden rounded bg-surface-2"><div className="h-full bg-primary transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} /></div>}
          {running && <div className="mt-1 font-mono text-[10px] text-muted-foreground">Waiting for the AI provider — the page updates by itself every few seconds.</div>}
        </div>
        {v.status === "PLANNED" && !running && <Button size="sm" onClick={() => gen.mutate(false)}>Generate keyframes</Button>}
      </div>

      {/* steps */}
      <ol className="flex flex-wrap items-center gap-2 px-8 pt-4 font-mono text-[11px] uppercase tracking-wider">
        {STEPS.map((s, i) => {
          const state = failed && i === step ? "fail" : i < step ? "done" : i === step ? "active" : "todo"
          return (
            <li key={s.key} className="flex items-center gap-2">
              <span className={cn("rounded-full border px-2 py-0.5", state === "done" && "border-ready/40 text-ready", state === "active" && "border-primary text-primary",
                state === "fail" && "border-fail text-fail", state === "todo" && "border-border text-muted-foreground")}>
                {state === "active" && running && <Loader2 className="mr-1 inline size-3 animate-spin" />}{s.label}
              </span>
              {i < STEPS.length - 1 && <span className="h-px w-5 bg-border" />}
            </li>
          )
        })}
      </ol>

      <div className="grid min-w-0 gap-8 px-8 py-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-6">
          {v.style_guide && <p className="rounded-md border border-border bg-surface-2 p-3 text-xs text-muted-foreground"><span className="font-mono text-primary">style guide</span> {v.style_guide}</p>}

          <section>
            <h2 className="mb-2 font-heading text-sm font-semibold">Keyframes · {v.keyframes.length || v.n_segments + 1}</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {(v.keyframes.length ? v.keyframes : Array.from({ length: v.n_segments + 1 }, (_, i) => ({ index: i, prompt: "", caption: null, status: "PLANNING", error: null, version: 0, image_url: null }) as LabKeyframe)).map(k => (
                <div key={k.index} className={cn("rounded-md border bg-card p-2", k.status === "FAILED" ? "border-fail/40" : "border-border")}>
                  <div className="relative aspect-[9/16] overflow-hidden rounded bg-surface-2">
                    {k.image_url ? <img src={`/api${k.image_url}`} alt="" className="h-full w-full object-cover" />
                      : <div className="grid h-full place-items-center px-2 text-center text-[11px] text-muted-foreground">
                        {k.status === "GENERATING" ? <span className="animate-pulse text-primary"><Loader2 className="mx-auto mb-1 size-4 animate-spin" />generating image…</span>
                          : k.status === "FAILED" ? <span className="text-fail">{k.error}</span>
                          : k.status === "PLANNING" ? <span className="animate-pulse">waiting for storyboard…</span>
                          : "waiting"}
                      </div>}
                    <span className="absolute left-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">{k.index === 0 ? "START" : k.index === v.n_segments ? "END" : `#${k.index}`}</span>
                    {k.version > 1 && <span className="absolute right-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">v{k.version}</span>}
                  </div>
                  <div className="mt-1 truncate text-xs" title={k.prompt}>{k.caption || k.prompt || "—"}</div>
                  <div className="mt-1 flex gap-1">
                    <Button size="sm" variant="outline" className="flex-1" disabled={running || !k.prompt} onClick={() => setEditing(k)}><Wand2 className="size-3.5" /> Edit & redo</Button>
                    <Button size="sm" variant="ghost" disabled={running || !k.prompt} onClick={() => regen.mutate({ index: k.index })} title="Regenerate with the same prompt"><RefreshCw className="size-3.5" /></Button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {v.segments.some(s => s.status !== "PENDING") && (
            <section className="min-w-0">
              <h2 className="mb-2 font-heading text-sm font-semibold">Segments · {v.segments.length} × {v.segment_seconds}s</h2>
              <div className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {v.segments.map(s => (
                  <div key={s.index} className={cn("min-w-0 overflow-hidden rounded-md border bg-card p-2.5", s.status === "FAILED" ? "border-fail/40" : s.status === "GENERATING" ? "border-primary/50" : "border-border")}>
                    <div className="flex items-center justify-between gap-2 font-mono text-[11px]">
                      <span>#{s.index + 1} · frames {s.from_index}→{s.to_index}</span>
                      <span className={cn("rounded border px-1.5 py-0.5 text-[10px]", s.status === "DONE" ? "border-ready/30 text-ready" : s.status === "FAILED" ? "border-fail/30 text-fail" : s.status === "GENERATING" ? "animate-pulse border-primary text-primary" : "border-border text-muted-foreground")}>{s.status === "GENERATING" ? "animating" : s.status.toLowerCase()}</span>
                    </div>
                    <p className="mt-1.5 line-clamp-2 break-words text-[11px] leading-snug text-muted-foreground" title={s.prompt ?? ""}>{s.prompt ?? "—"}</p>
                    <div className="mt-1.5 flex items-center justify-between font-mono text-[10px] text-muted-foreground">
                      <span>{s.duration ? `${s.duration.toFixed(1)}s` : `${v.segment_seconds}s`}{s.version > 1 ? ` · v${s.version}` : ""}</span>
                      {s.video_url && <a className="text-primary underline" href={`/api${s.video_url}`} target="_blank" rel="noreferrer">open clip</a>}
                    </div>
                    {s.last_edit && <p className="mt-1 line-clamp-1 text-[10px] text-primary" title={s.last_edit}>edit: {s.last_edit}</p>}
                    {s.error && <p className="mt-1 line-clamp-2 break-words text-[10px] text-fail" title={s.error}>{s.error}</p>}
                    <Button size="sm" variant="outline" className="mt-2 w-full" disabled={running || !allImages} onClick={() => setEditingSeg(s)}><Wand2 className="size-3.5" /> Edit & redo</Button>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section>
            <h2 className="mb-2 font-heading text-sm font-semibold">Activity</h2>
            <ul className="max-h-72 min-w-0 space-y-1 overflow-y-auto overflow-x-hidden rounded-md border border-border bg-surface-2 p-3 font-mono text-[11px]">
              {[...v.events].reverse().map((e, i) => (
                <li key={i} className={cn("flex gap-3", e.level === "error" && "text-fail", e.level === "success" && "text-ready", e.level === "warning" && "text-primary")}>
                  <span className="shrink-0 text-muted-foreground">{new Date(e.created_at).toLocaleTimeString()}</span>
                  <span className="w-28 shrink-0 truncate uppercase text-muted-foreground" title={e.stage}>{e.stage.replace(/_/g, " ")}</span>
                  <span className="min-w-0 break-words">{e.message}</span>
                </li>
              ))}
              {v.events.length === 0 && <li className="text-muted-foreground">No activity yet.</li>}
            </ul>
          </section>
        </div>

        <div className="space-y-3">
          <div className="aspect-[9/16] w-full overflow-hidden rounded-lg border border-border bg-black">
            {v.video_url ? <video key={v.updated_at} src={lab.videoUrl(v.id)} controls playsInline className="h-full w-full" />
              : <div className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">
                {v.status === "ANIMATING" ? <span><Loader2 className="mx-auto mb-2 size-5 animate-spin text-primary" />Animating segments…</span>
                  : allImages ? "Keyframes ready. Press “Animate video”." : "The video appears here after step 4."}
              </div>}
          </div>
          {v.video_url && <a href={lab.videoUrl(v.id)} download={`${v.id}.mp4`} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}><Download className="size-4" /> Download MP4 {v.final_duration ? `· ${v.final_duration.toFixed(1)}s` : ""}</a>}
        </div>
      </div>

      <EditKeyframeDialog kf={editing} video={v} onClose={() => setEditing(null)} onSubmit={(index, prompt) => regen.mutate({ index, prompt })} busy={regen.isPending} />
      <EditSegmentDialog seg={editingSeg} supportsEdit={v.supports_edit} onClose={() => setEditingSeg(null)} busy={redoSeg.isPending}
        onSubmit={(index, body) => redoSeg.mutate({ index, body })} />
      <Dialog open={compareOpen} onOpenChange={o => { if (!o) setCompareOpen(false) }}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle className="font-heading">Compare with another model</DialogTitle>
            <DialogDescription>Clones this video (same storyboard and keyframes when the clip count matches) and renders it with the chosen model. Current: {v.provider_label}.</DialogDescription>
          </DialogHeader>
          <CompareBody exclude={v.video_provider} busy={cloneMut.isPending} onSubmit={p => cloneMut.mutate(p)} />
        </DialogContent>
      </Dialog>
      <ChangeLengthDialog open={lengthOpen} video={v} onClose={() => setLengthOpen(false)} busy={setLen.isPending} onSubmit={d => setLen.mutate(d)} />
    </div>
  )
}

function CompareBody({ exclude, busy, onSubmit }: { exclude: string | null; busy: boolean; onSubmit: (p: string) => void }) {
  const [p, setP] = useState("")
  return (
    <div className="space-y-3">
      <ProviderSelect value={p} onChange={setP} exclude={exclude} />
      <div className="flex justify-end"><Button disabled={!p || busy} onClick={() => onSubmit(p)}><GitCompare className="size-4" /> Clone & render</Button></div>
    </div>
  )
}

function EditSegmentDialog({ seg, supportsEdit, onClose, onSubmit, busy }: { seg: LabSegment | null; supportsEdit: boolean; onClose: () => void; busy: boolean
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

function ChangeLengthDialog({ open, video, onClose, onSubmit, busy }: { open: boolean; video: LabVideo; onClose: () => void; onSubmit: (d: number) => void; busy: boolean }) {
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

function EditKeyframeDialog({ kf, video, onClose, onSubmit, busy }: { kf: LabKeyframe | null; video: LabVideo; onClose: () => void; onSubmit: (i: number, p: string) => void; busy: boolean }) {
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
