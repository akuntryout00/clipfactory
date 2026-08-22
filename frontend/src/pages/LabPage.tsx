import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FlaskConical, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { fmtDate, lab } from "@/lib/api"
import type { LabVideo } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { ProviderSelect, Stat } from "@/components/lab/ProviderSelect"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { useConfirm } from "@/components/ConfirmDialog"

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
  const confirm = useConfirm()
  const [open, setOpen] = useState(false)
  const { data } = useQuery({ queryKey: ["lab"], queryFn: lab.list, refetchInterval: q => (q.state.data?.some(v => RUNNING.has(v.status)) ? 4000 : 20000) })
  const del = useMutation({ mutationFn: lab.delete, onSuccess: () => { toast.success("Lab video deleted"); qc.invalidateQueries({ queryKey: ["lab"] }) }, onError: e => toast.error(e.message) })
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
            <p className="mt-2 text-sm text-muted-foreground">Describe it → AI paints the keyframes (OpenAI) → a video model of your choice (Gemini Omni, Seedance, MiniMax, Kling, Veo) animates each step → one 9:16 MP4. You review the keyframes before anything is animated.</p>
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
                      onClick={async e => { e.stopPropagation(); if (await confirm({ title: "Delete this Lab video?", subject: title(v.prompt), description: "Keyframes, segments and the final clip are removed.", confirmLabel: "Delete video" })) del.mutate(v.id) }}><Trash2 className="size-3.5" /></span>
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

function NewVideoDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [prompt, setPrompt] = useState("")
  const [style, setStyle] = useState("")
  const [duration, setDuration] = useState(18)
  const [provider, setProvider] = useState("omni")
  const { data: est } = useQuery({ queryKey: ["lab-estimate", provider, duration], queryFn: () => lab.estimate(provider, duration), enabled: !!provider, placeholderData: prev => prev })
  const create = useMutation({
    mutationFn: () => lab.create({ prompt: prompt.trim(), target_duration: duration, style: style.trim() || null, video_provider: provider }),
    onSuccess: v => { toast.success("Started — planning the storyboard"); onClose(); nav(`/lab/${v.id}`) },
    onError: e => toast.error(e.message),
  })
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="font-heading">New AI video</DialogTitle>
          <DialogDescription>Write what should happen, pick a model and a length. You'll review the keyframes before animation.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={e => { e.preventDefault(); if (prompt.trim().length >= 5) create.mutate() }}>
          <div>
            <Label htmlFor="lp" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">1 · What video do you want?</Label>
            <Textarea id="lp" rows={9} autoFocus value={prompt} onChange={e => setPrompt(e.target.value)} className="min-h-[200px] resize-none text-[15px] leading-relaxed"
              placeholder="A solo founder's morning in a sunlit cafe: a steaming coffee, a laptop opening, typing, then stepping out into a bright city street. Warm cinematic light, calm and motivating." />
          </div>
          <div className="grid gap-4 sm:grid-cols-[1fr_1fr]">
            <div>
              <Label htmlFor="ls" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Visual style (optional)</Label>
              <Input id="ls" value={style} onChange={e => setStyle(e.target.value)} placeholder="cinematic realistic · anime · claymation…" className="h-[58px]" />
            </div>
            <div>
              <Label className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">2 · Video model</Label>
              <ProviderSelect value={provider} onChange={setProvider} />
            </div>
          </div>
          <div className="rounded-lg border border-border bg-surface-2 px-4 py-3">
            <div className="grid items-center gap-4 sm:grid-cols-[1fr_auto]">
              <div>
                <div className="flex items-baseline justify-between">
                  <Label htmlFor="ld" className="text-xs uppercase tracking-wider text-muted-foreground">3 · Length</Label>
                  <span className="font-heading text-xl font-bold">{duration}<span className="text-sm font-normal text-muted-foreground">s</span></span>
                </div>
                <input id="ld" type="range" min={3} max={25} step={1} value={duration} onChange={e => setDuration(Number(e.target.value))} className="scrub mt-1 w-full" />
                <div className="flex justify-between font-mono text-[10px] text-muted-foreground"><span>3s</span><span>25s</span></div>
              </div>
              {est && (
                <div className="grid grid-cols-3 gap-2 text-center">
                  <Stat label="keyframes" value={String(est.keyframes)} sub={`$${est.image_cost.toFixed(2)}`} />
                  <Stat label="clips" value={`${est.n_segments} × ${est.segment_seconds}s`} sub={est.video_seconds !== duration ? `renders ${est.video_seconds}s` : `$${est.price_per_second.toFixed(2)}/s`} />
                  <Stat label="video" value={`$${est.video_cost.toFixed(2)}`} sub={est.label} />
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-[11px] text-muted-foreground">{est ? "Estimate uses list prices; retries and re-dos are extra." : ""}</span>
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" size="lg" disabled={prompt.trim().length < 5 || create.isPending}>
              <FlaskConical className="size-4" /> {create.isPending ? "Starting…" : "Create video"}{est ? <span className="ml-1 rounded bg-primary-foreground/15 px-1.5 font-mono text-xs">≈ ${est.total.toFixed(2)}</span> : null}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
