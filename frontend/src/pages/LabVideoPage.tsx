import { useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Download, Film, RefreshCw, Wand2 } from "lucide-react"
import { toast } from "sonner"
import { fmtDate, lab } from "@/lib/api"
import type { LabKeyframe, LabVideo } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { Button, buttonVariants } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

const RUNNING = new Set(["GENERATING_IMAGES", "ANIMATING"])

export default function LabVideoPage() {
  const { id = "" } = useParams()
  const qc = useQueryClient()
  const { data: v, isLoading } = useQuery({ queryKey: ["lab", id], queryFn: () => lab.get(id), refetchInterval: q => (q.state.data && RUNNING.has(q.state.data.status) ? 2500 : false) })
  const [editing, setEditing] = useState<LabKeyframe | null>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ["lab", id] }); qc.invalidateQueries({ queryKey: ["lab"] }) }
  const gen = useMutation({ mutationFn: (onlyMissing: boolean) => lab.generateImages(id, onlyMissing), onSuccess: () => { toast.success("Generating keyframes"); refresh() }, onError: e => toast.error(e.message) })
  const regen = useMutation({ mutationFn: ({ index, prompt }: { index: number; prompt?: string | null }) => lab.regenerate(id, index, prompt), onSuccess: () => { toast.success("Regenerating keyframe"); setEditing(null); refresh() }, onError: e => toast.error(e.message) })
  const anim = useMutation({ mutationFn: (force: boolean) => lab.animate(id, force), onSuccess: () => { toast.success("Animating — this takes a few minutes"); refresh() }, onError: e => toast.error(e.message) })
  if (isLoading || !v) return <div className="p-8 text-muted-foreground">Loading…</div>
  const running = RUNNING.has(v.status)
  const allImages = v.keyframes.length > 0 && v.keyframes.every(k => k.status === "DONE")
  const step = v.status === "DONE" ? 3 : allImages ? 2 : 1

  return (
    <div>
      <PageHeader eyebrow={<Link to="/lab" className="inline-flex items-center gap-1 hover:text-foreground"><ArrowLeft className="size-3" /> AI Lab</Link> as unknown as string}
        title={v.prompt.length > 90 ? v.prompt.slice(0, 90) + "…" : v.prompt}
        actions={<>
          <Button variant="outline" size="sm" disabled={running} onClick={() => gen.mutate(false)}><RefreshCw className="size-4" /> Regenerate all images</Button>
          <Button size="sm" disabled={running || !allImages} onClick={() => anim.mutate(v.status === "DONE")}><Film className="size-4" /> {v.status === "DONE" ? "Animate again" : "Animate video"}</Button>
        </>}>
        <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[11px] text-muted-foreground">
          <span className={cn("rounded border px-1.5 py-0.5", v.status === "DONE" ? "border-ready/30 text-ready" : v.status === "FAILED" ? "border-fail/30 text-fail" : "border-border")}>{running && <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-primary" />}{v.status.replace(/_/g, " ")}</span>
          <span>{v.id}</span><span>{v.target_duration}s target · {v.n_segments} × {v.segment_seconds}s</span>
          <span>images {v.image_model} · video {v.video_model}</span><span>{fmtDate(v.created_at)}</span>
        </div>
        {(v.stage_message || v.error) && <p className={cn("mt-1 text-xs", v.error ? "text-fail" : "text-muted-foreground")}>{v.error ?? v.stage_message}</p>}
      </PageHeader>

      {/* steps */}
      <ol className="flex items-center gap-2 px-8 pt-5 font-mono text-[11px] uppercase tracking-wider">
        {["1 · Describe", "2 · Keyframes (OpenAI)", "3 · Animate (Google)", "4 · Video"].map((label, i) => (
          <li key={label} className="flex items-center gap-2">
            <span className={cn("rounded-full border px-2 py-0.5", i < step ? "border-ready/40 text-ready" : i === step ? "border-primary text-primary" : "border-border text-muted-foreground")}>{label}</span>
            {i < 3 && <span className="h-px w-6 bg-border" />}
          </li>
        ))}
      </ol>

      <div className="grid gap-8 px-8 py-6 xl:grid-cols-[1fr_320px]">
        <div className="space-y-6">
          {v.style_guide && <p className="rounded-md border border-border bg-surface-2 p-3 text-xs text-muted-foreground"><span className="font-mono text-primary">style guide</span> {v.style_guide}</p>}
          <section>
            <h2 className="mb-2 font-heading text-sm font-semibold">Keyframes · {v.keyframes.length}</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {v.keyframes.map(k => (
                <div key={k.index} className={cn("rounded-md border bg-card p-2", k.status === "FAILED" ? "border-fail/40" : "border-border")}>
                  <div className="relative aspect-[9/16] overflow-hidden rounded bg-surface-2">
                    {k.image_url ? <img src={`/api${k.image_url}`} alt="" className="h-full w-full object-cover" />
                      : <div className="grid h-full place-items-center text-[11px] text-muted-foreground">{k.status === "GENERATING" ? <span className="animate-pulse text-primary">generating…</span> : k.status === "FAILED" ? <span className="text-fail px-2 text-center">{k.error}</span> : "pending"}</div>}
                    <span className="absolute left-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">{k.index === 0 ? "START" : k.index === v.keyframes.length - 1 ? "END" : `#${k.index}`}</span>
                    {k.version > 1 && <span className="absolute right-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">v{k.version}</span>}
                  </div>
                  <div className="mt-1 truncate text-xs" title={k.prompt}>{k.caption || k.prompt}</div>
                  <div className="mt-1 flex gap-1">
                    <Button size="sm" variant="outline" className="flex-1" disabled={running} onClick={() => setEditing(k)}><Wand2 className="size-3.5" /> Edit & redo</Button>
                    <Button size="sm" variant="ghost" disabled={running} onClick={() => regen.mutate({ index: k.index })} title="Regenerate with the same prompt"><RefreshCw className="size-3.5" /></Button>
                  </div>
                </div>
              ))}
            </div>
          </section>
          {v.segments.some(s => s.status !== "PENDING") && (
            <section>
              <h2 className="mb-2 font-heading text-sm font-semibold">Segments · {v.segments.length} × {v.segment_seconds}s</h2>
              <ul className="divide-y divide-border rounded-md border border-border">
                {v.segments.map(s => (
                  <li key={s.index} className="flex items-center gap-3 p-2 text-xs">
                    <span className="font-mono">#{s.index + 1} · frames {s.from_index}→{s.to_index}</span>
                    <span className={cn("rounded border px-1.5 font-mono text-[10px]", s.status === "DONE" ? "border-ready/30 text-ready" : s.status === "FAILED" ? "border-fail/30 text-fail" : s.status === "GENERATING" ? "border-primary text-primary animate-pulse" : "border-border text-muted-foreground")}>{s.status}</span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">{s.prompt}</span>
                    {s.error && <span className="text-fail">{s.error}</span>}
                    {s.video_url && <a className="text-primary underline" href={`/api${s.video_url}`} target="_blank" rel="noreferrer">open</a>}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <div className="space-y-3">
          <div className="aspect-[9/16] w-full overflow-hidden rounded-lg border border-border bg-black">
            {v.video_url ? <video key={v.updated_at} src={lab.videoUrl(v.id)} controls playsInline className="h-full w-full" />
              : <div className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">{v.status === "ANIMATING" ? "Animating segments…" : allImages ? "Keyframes ready. Press “Animate video”." : "The video appears here after step 3."}</div>}
          </div>
          {v.video_url && <a href={lab.videoUrl(v.id)} download={`${v.id}.mp4`} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}><Download className="size-4" /> Download MP4 {v.final_duration ? `· ${v.final_duration.toFixed(1)}s` : ""}</a>}
        </div>
      </div>

      <EditKeyframeDialog kf={editing} video={v} onClose={() => setEditing(null)} onSubmit={(index, prompt) => regen.mutate({ index, prompt })} busy={regen.isPending} />
    </div>
  )
}

function EditKeyframeDialog({ kf, video, onClose, onSubmit, busy }: { kf: LabKeyframe | null; video: LabVideo; onClose: () => void; onSubmit: (i: number, p: string) => void; busy: boolean }) {
  const [p, setP] = useState("")
  const cur = kf ? (p || kf.prompt) : ""
  return (
    <Dialog open={!!kf} onOpenChange={o => { if (!o) { setP(""); onClose() } }}>
      <DialogContent className="sm:max-w-3xl">
        {kf && (<>
          <DialogHeader><DialogTitle className="font-heading">Keyframe {kf.index === 0 ? "START" : kf.index === video.keyframes.length - 1 ? "END" : `#${kf.index}`} — edit prompt & regenerate</DialogTitle></DialogHeader>
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
