import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FlaskConical, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { fmtDate, lab } from "@/lib/api"
import type { LabVideo } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

const RUNNING = new Set(["PLANNING", "GENERATING_IMAGES", "ANIMATING"])
const STATUS_STYLE: Record<string, string> = {
  DONE: "text-ready border-ready/30 bg-ready/10", FAILED: "text-fail border-fail/30 bg-fail/10",
  IMAGES_READY: "text-primary border-primary/40 bg-primary/10", PLANNED: "text-muted-foreground border-border",
}
const STATUS_LABEL: Record<string, string> = {
  PLANNING: "planning", PLANNED: "planned", GENERATING_IMAGES: "making keyframes", IMAGES_READY: "review keyframes", ANIMATING: "animating", DONE: "ready", FAILED: "failed",
}
const title = (s: string) => (s.length > 50 ? s.slice(0, 50).trimEnd() + "…" : s)

export default function LabPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const { data } = useQuery({ queryKey: ["lab"], queryFn: lab.list, refetchInterval: q => (q.state.data?.some(v => RUNNING.has(v.status)) ? 4000 : 20000) })
  const del = useMutation({ mutationFn: lab.delete, onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["lab"] }) }, onError: e => toast.error(e.message) })
  const videos = data ?? []

  return (
    <div>
      <PageHeader eyebrow="Separate module · fully AI-generated" title="AI Lab" />

      {/* hero: one action */}
      <section className="px-8 pt-8">
        <div className="relative overflow-hidden rounded-xl border border-border bg-card px-8 py-14 text-center">
          <div className="pointer-events-none absolute inset-0 opacity-60" style={{ background: "radial-gradient(600px 220px at 50% 0%, rgba(255,229,0,0.10), transparent 70%)" }} />
          <div className="relative mx-auto max-w-xl">
            <div className="mx-auto mb-4 grid size-12 place-items-center rounded-lg bg-primary text-primary-foreground"><FlaskConical className="size-6" /></div>
            <h2 className="font-heading text-2xl font-bold">Make a vertical video from a sentence</h2>
            <p className="mt-2 text-sm text-muted-foreground">Describe it → AI paints the keyframes (OpenAI) → AI animates each step (Gemini Omni) → one 9:16 MP4. You review the keyframes before anything is animated.</p>
            <Button size="lg" className="mt-6 h-12 px-8 text-base" onClick={() => setOpen(true)}><Plus className="size-5" /> New video</Button>
          </div>
        </div>
      </section>

      {/* list */}
      <section className="px-8 py-8">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="font-heading text-sm font-semibold">Your videos</h2>
          <span className="font-mono text-[11px] text-muted-foreground">{videos.length} total · {videos.filter(v => v.status === "DONE").length} ready</span>
        </div>
        {videos.length === 0 && <p className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">No videos yet — press <b>New video</b> to start your first one.</p>}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {videos.map((v: LabVideo) => {
            const thumbs = v.keyframes.filter(k => k.image_url)
            const running = RUNNING.has(v.status)
            return (
              <button key={v.id} type="button" onClick={() => nav(`/lab/${v.id}`)}
                className="group overflow-hidden rounded-lg border border-border bg-card text-left transition-colors hover:border-primary/60 focus-visible:outline-2 focus-visible:outline-ring">
                <div className="flex h-40 w-full gap-0.5 bg-surface-2">
                  {thumbs.length ? thumbs.slice(0, 4).map(k => <img key={k.index} src={`/api${k.image_url}`} alt="" className="h-full min-w-0 flex-1 object-cover" />)
                    : <div className="grid h-full w-full place-items-center text-[11px] text-muted-foreground">{running ? <span className="animate-pulse text-primary">generating…</span> : "no keyframes yet"}</div>}
                </div>
                <div className="p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="font-medium leading-snug" title={v.prompt}>{title(v.prompt)}</div>
                    <span className={cn("shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px]", STATUS_STYLE[v.status] ?? "text-primary border-primary/40")}>
                      {running && <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-primary" />}{STATUS_LABEL[v.status] ?? v.status.toLowerCase()}
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center justify-between font-mono text-[11px] text-muted-foreground">
                    <span className="truncate"><span className="text-foreground/80">{v.provider_label ?? v.video_model}</span> · {v.final_duration ? `${v.final_duration.toFixed(1)}s` : `${v.target_duration}s`} · {v.n_segments}×{v.segment_seconds}s · {fmtDate(v.created_at)}</span>
                    <span role="button" aria-label="Delete" className="rounded p-1 hover:bg-accent hover:text-fail"
                      onClick={e => { e.stopPropagation(); if (confirm(`Delete "${title(v.prompt)}"?`)) del.mutate(v.id) }}><Trash2 className="size-3.5" /></span>
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <NewVideoDialog open={open} onClose={() => setOpen(false)} />
    </div>
  )
}

export function ProviderSelect({ value, onChange, exclude }: { value: string; onChange: (v: string) => void; exclude?: string | null }) {
  const { data } = useQuery({ queryKey: ["lab-providers"], queryFn: lab.providers })
  const rows = (data ?? []).filter(p => p.id !== "fake" || import.meta.env.DEV)
  return (
    <div className="grid gap-1.5">
      {rows.filter(p => p.id !== exclude).map(p => (
        <label key={p.id} className={cn("flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2 text-xs", value === p.id ? "border-primary bg-primary/5" : "border-border hover:bg-accent/40", !p.available && "opacity-50")}>
          <input type="radio" name="provider" className="scrub mt-0.5" checked={value === p.id} disabled={!p.available} onChange={() => onChange(p.id)} />
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2"><b>{p.label}</b><span className="font-mono text-[10px] text-muted-foreground">{p.model}</span>
              {p.supports_edit && <span className="rounded border border-primary/40 px-1 font-mono text-[9px] text-primary">clip edit</span>}</span>
            <span className="block text-muted-foreground">{p.note} · clips ≤{p.max_seconds}s · {p.price_hint}{!p.available && p.needs ? ` · needs ${p.needs} in .env` : ""}</span>
          </span>
        </label>
      ))}
    </div>
  )
}

function NewVideoDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [style, setStyle] = useState("")
  const [duration, setDuration] = useState(18)
  const [provider, setProvider] = useState("omni")
  const { data: provs } = useQuery({ queryKey: ["lab-providers"], queryFn: lab.providers })
  const maxSeg = provs?.find(p => p.id === provider)?.max_seconds ?? 10
  const segs = Math.max(2, Math.ceil(duration / maxSeg)), segLen = Math.max(4, Math.min(maxSeg, Math.round(duration / segs)))
  const create = useMutation({
    mutationFn: () => lab.create({ prompt: prompt.trim(), target_duration: duration, style: style.trim() || null, video_provider: provider }),
    onSuccess: v => { toast.success("Started — planning the storyboard"); onClose(); nav(`/lab/${v.id}`) },
    onError: e => toast.error(e.message),
  })
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading">New AI video</DialogTitle>
          <DialogDescription>Write what should happen, pick a length. You'll review the keyframes before animation.</DialogDescription>
        </DialogHeader>
        <form className="space-y-5" onSubmit={e => { e.preventDefault(); if (prompt.trim().length >= 5) create.mutate() }}>
          <div>
            <Label htmlFor="lp" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">What video do you want?</Label>
            <Textarea id="lp" rows={5} autoFocus value={prompt} onChange={e => setPrompt(e.target.value)}
              placeholder="A solo founder's morning in a sunlit cafe: a steaming coffee, a laptop opening, typing, then stepping out into a bright city street. Warm cinematic light, calm and motivating." />
          </div>
          <div>
            <Label className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Video model (animates the keyframes)</Label>
            <ProviderSelect value={provider} onChange={setProvider} />
          </div>
          <div className="grid grid-cols-[1fr_200px] gap-4">
            <div>
              <Label htmlFor="ls" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Visual style (optional)</Label>
              <Input id="ls" value={style} onChange={e => setStyle(e.target.value)} placeholder="cinematic realistic · anime · claymation…" />
            </div>
            <div>
              <Label htmlFor="ld" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Length · <span className="font-mono text-foreground">{duration}s</span></Label>
              <input id="ld" type="range" min={15} max={25} step={1} value={duration} onChange={e => setDuration(Number(e.target.value))} className="scrub w-full" />
              <div className="font-mono text-[11px] text-muted-foreground">{segs + 1} keyframes · {segs} × {segLen}s clips</div>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" size="lg" disabled={prompt.trim().length < 5 || create.isPending}><FlaskConical className="size-4" /> {create.isPending ? "Starting…" : "Create video"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
