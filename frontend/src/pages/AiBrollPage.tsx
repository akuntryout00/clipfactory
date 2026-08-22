import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Camera, Check, Clapperboard, ImageOff, RefreshCw, Sparkles, Trash2, X } from "lucide-react"
import { toast } from "sonner"
import { aibroll, api, fmtDate, lab, media } from "@/lib/api"
import { personaLabel, usePersona } from "@/lib/persona"
import type { AiBrollJob, ShotlistItem } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { ProviderSelect } from "@/components/lab/ProviderSelect"
import { useConfirm } from "@/components/ConfirmDialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

const RUNNING = new Set(["QUEUED", "KEYFRAME", "ANIMATING", "IMPORTING"])
const DEFAULT_PROVIDER = "fal:seedance-2.0"

/**
 * AI B-roll: describe a shot (or come from the shot list with everything prefilled), pick a video model and length,
 * optionally keep the persona's real face, generate → the clip lands in the persona's B-roll library.
 */
export default function AiBrollPage() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const confirm = useConfirm()
  const [params, setParams] = useSearchParams()
  const { activeId, active } = usePersona()
  const itemId = params.get("item")
  const { data: shotlist } = useQuery({ queryKey: ["shotlist", activeId], queryFn: () => api.shotlist(activeId), enabled: !!activeId })
  const item: ShotlistItem | undefined = useMemo(() => shotlist?.items.find(i => i.id === itemId), [shotlist, itemId])
  const { data: imgStatus } = useQuery({ queryKey: ["persona-image", activeId], queryFn: () => aibroll.personaImageStatus(activeId), enabled: !!activeId })
  const { data: providers } = useQuery({ queryKey: ["lab-providers"], queryFn: lab.providers })

  const [prompt, setPrompt] = useState("")
  const [title, setTitle] = useState("")
  const [category, setCategory] = useState("ai")
  const [shot, setShot] = useState("")
  const [action, setAction] = useState("")
  const [location, setLocation] = useState("")
  const [mood, setMood] = useState("")
  const [tags, setTags] = useState("")
  const [provider, setProvider] = useState(DEFAULT_PROVIDER)
  const [seconds, setSeconds] = useState(5)
  const [useFace, setUseFace] = useState(false)
  const [customPhoto, setCustomPhoto] = useState<File | null>(null)
  const [imgV, setImgV] = useState(0)
  const photoRef = useRef<HTMLInputElement>(null)
  const customRef = useRef<HTMLInputElement>(null)

  // prefill from the shot-list item
  useEffect(() => {
    if (!item) return
    setPrompt(item.description); setTitle(item.title); setCategory(item.category)
    setShot(item.shot ?? ""); setAction(item.action ?? ""); setLocation(item.location ?? ""); setMood(item.mood ?? ""); setTags(item.tags.join(", "))
  }, [item])
  useEffect(() => { if (imgStatus) setUseFace(u => u && imgStatus.has_image) }, [imgStatus])

  const meta = providers?.find(p => p.id === provider)
  const maxSec = Math.min(15, meta?.max_seconds ?? 10), minSec = Math.max(3, meta?.min_seconds ?? 3)
  useEffect(() => { setSeconds(s => Math.max(minSec, Math.min(maxSec, s))) }, [minSec, maxSec])
  const withRef = useFace && (!!imgStatus?.has_image || !!customPhoto) || !!customPhoto
  const { data: est } = useQuery({ queryKey: ["aib-estimate", provider, seconds, withRef], queryFn: () => aibroll.estimate(provider, seconds, withRef), enabled: !!provider })

  const { data: jobs } = useQuery({
    queryKey: ["aib-jobs", activeId], queryFn: () => aibroll.jobs(activeId), enabled: !!activeId,
    refetchInterval: q => (q.state.data?.some(j => RUNNING.has(j.status)) ? 3000 : 20000),
  })
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["aib-jobs"] }); qc.invalidateQueries({ queryKey: ["assets"] }); qc.invalidateQueries({ queryKey: ["shotlist"] }) }

  const create = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append("persona_id", activeId); fd.append("prompt", prompt.trim()); if (title.trim()) fd.append("title", title.trim())
      fd.append("category", category.trim() || "ai"); if (shot) fd.append("shot", shot); if (action) fd.append("action", action)
      if (location) fd.append("location", location); if (mood) fd.append("mood", mood); fd.append("tags", tags)
      fd.append("seconds", String(seconds)); fd.append("video_provider", provider)
      fd.append("use_reference", String(useFace && !!imgStatus?.has_image && !customPhoto))
      if (customPhoto) fd.append("reference", customPhoto)
      if (itemId) fd.append("shotlist_item_id", itemId)
      return aibroll.create(fd)
    },
    onSuccess: j => { toast.success(`Generating "${j.title}" — ${j.seconds}s · ${j.video_provider}`); invalidate(); setCustomPhoto(null) },
    onError: e => toast.error(e.message),
  })
  const uploadPhoto = useMutation({
    mutationFn: (f: File) => aibroll.uploadPersonaImage(activeId, f),
    onSuccess: () => { toast.success("Persona photo saved"); setImgV(v => v + 1); setUseFace(true); qc.invalidateQueries({ queryKey: ["persona-image", activeId] }) },
    onError: e => toast.error(e.message),
  })
  const removePhoto = useMutation({
    mutationFn: () => aibroll.deletePersonaImage(activeId),
    onSuccess: () => { toast.success("Persona photo removed"); setUseFace(false); qc.invalidateQueries({ queryKey: ["persona-image", activeId] }) },
    onError: e => toast.error(e.message),
  })
  const retry = useMutation({ mutationFn: aibroll.retry, onSuccess: () => { toast.success("Retrying"); invalidate() }, onError: e => toast.error(e.message) })
  const del = useMutation({ mutationFn: aibroll.delete, onSuccess: () => { toast.success("Job deleted"); invalidate() }, onError: e => toast.error(e.message) })

  const valid = !!activeId && prompt.trim().length >= 5 && !!provider && (meta?.available ?? true)

  return (
    <div>
      <PageHeader eyebrow="Generated footage" title="AI B-roll">
        <p className="mt-1 text-sm text-muted-foreground">Describe a shot, pick a video model and length, generate — the clip is added to <span className="text-foreground">{personaLabel(active)}</span>'s B-roll library (approved, tagged{itemId ? ", assigned to the shot you picked" : ""}). Optionally keep the persona's real face.</p>
      </PageHeader>
      <div className="grid gap-6 px-8 py-6 xl:grid-cols-[1fr_380px]">
        <form className="space-y-5" onSubmit={e => { e.preventDefault(); if (valid) create.mutate() }}>
          {item && (
            <div className="flex items-start justify-between gap-3 rounded-md border border-primary/40 bg-primary/5 p-3 text-sm">
              <div><span className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">from the shot list</span><div className="font-medium">{item.title} <span className="font-mono text-[11px] text-muted-foreground">{item.category} · {item.filled}/{item.count}</span></div></div>
              <button type="button" className="text-muted-foreground hover:text-foreground" onClick={() => { params.delete("item"); setParams(params) }} title="Detach from the shot"><X className="size-4" /></button>
            </div>
          )}
          <div>
            <Label htmlFor="aib-prompt" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">What should the clip show?</Label>
            <Textarea id="aib-prompt" rows={4} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Close-up of hands typing on a laptop at a cafe table, a cup of coffee next to it, morning light from the window" className="text-base" />
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_160px]">
            <div><Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Title</Label><Input value={title} onChange={e => setTitle(e.target.value)} placeholder="short label for the library" /></div>
            <div><Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Folder</Label><Input value={category} onChange={e => setCategory(e.target.value)} className="font-mono" placeholder="ai" /></div>
          </div>
          <div className="grid gap-3 sm:grid-cols-4">
            <div><Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Shot</Label>
              <select value={shot} onChange={e => setShot(e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm"><option value="">—</option>{["close", "medium", "wide"].map(s => <option key={s}>{s}</option>)}</select></div>
            <div><Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Action</Label><Input value={action} onChange={e => setAction(e.target.value)} className="font-mono" placeholder="typing_laptop" /></div>
            <div><Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Location</Label><Input value={location} onChange={e => setLocation(e.target.value)} placeholder="cafe" /></div>
            <div><Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Mood</Label>
              <select value={mood} onChange={e => setMood(e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm"><option value="">—</option>{["neutral", "focused", "stressed", "relaxed", "happy", "energetic"].map(s => <option key={s}>{s}</option>)}</select></div>
          </div>
          <div><Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Tags</Label><Input value={tags} onChange={e => setTags(e.target.value)} placeholder="laptop, cafe, typing" /></div>

          <div className="grid gap-4 rounded-md border border-border bg-card p-4 sm:grid-cols-[1fr_200px]">
            <div>
              <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Video model</Label>
              <ProviderSelect value={provider} onChange={setProvider} />
            </div>
            <div>
              <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Length · <span className="font-mono text-foreground">{seconds}s</span></Label>
              <input type="range" min={minSec} max={maxSec} step={1} value={seconds} onChange={e => setSeconds(Number(e.target.value))} className="scrub w-full" />
              <div className="flex justify-between font-mono text-[11px] text-muted-foreground"><span>{minSec}s</span><span>{maxSec}s</span></div>
            </div>
          </div>

          <div className="rounded-md border border-border bg-card p-4">
            <div className="flex items-start gap-4">
              <div className="relative size-20 shrink-0 overflow-hidden rounded-md border border-border bg-surface-2">
                {imgStatus?.has_image ? <img src={media.personaImage(activeId, imgV)} alt="" className="h-full w-full object-cover" /> : <div className="grid h-full place-items-center text-muted-foreground"><ImageOff className="size-5" /></div>}
              </div>
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-heading font-semibold">Persona photo</span>
                  <input ref={photoRef} type="file" accept="image/*" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) uploadPhoto.mutate(f); e.target.value = "" }} />
                  <Button type="button" size="sm" variant="outline" onClick={() => photoRef.current?.click()} disabled={uploadPhoto.isPending}><Camera className="size-3.5" /> {imgStatus?.has_image ? "Replace" : "Upload photo"}</Button>
                  {imgStatus?.has_image && <Button type="button" size="sm" variant="ghost" onClick={() => removePhoto.mutate()}><Trash2 className="size-3.5" /> Remove</Button>}
                </div>
                <label className={cn("flex items-start gap-2 text-sm", !imgStatus?.has_image && !customPhoto && "opacity-60")}>
                  <input type="checkbox" className="scrub mt-0.5 size-4" checked={useFace || !!customPhoto} disabled={!imgStatus?.has_image && !customPhoto} onChange={e => setUseFace(e.target.checked)} />
                  <span><b>Use this face in the scene</b> — the person from the photo is placed into the scene you described (face, hair and build kept; the photo's background is not reused), the start frame is made at high quality, and the video model keeps the face unchanged. Off = a generic person / no person. Works best with a front-facing, well-lit photo.</span>
                </label>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input ref={customRef} type="file" accept="image/*" className="hidden" onChange={e => { const f = e.target.files?.[0] ?? null; setCustomPhoto(f); e.target.value = "" }} />
                  <button type="button" className="underline-offset-2 hover:underline" onClick={() => customRef.current?.click()}>Use a different photo for this clip only</button>
                  {customPhoto && <span className="flex items-center gap-1 font-mono">{customPhoto.name} <button type="button" onClick={() => setCustomPhoto(null)}><X className="size-3" /></button></span>}
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3">
            <p className="font-mono text-[11px] text-muted-foreground">{est ? `≈ $${est.total.toFixed(2)} (video $${est.video_cost.toFixed(2)} + start frame $${est.image_cost.toFixed(2)})` : ""}{meta && !meta.available ? ` · needs ${meta.needs}` : ""}</p>
            <Button type="submit" size="lg" disabled={!valid || create.isPending}><Sparkles className="size-4" /> {create.isPending ? "Starting…" : `Generate ${seconds}s clip`}</Button>
          </div>
        </form>

        <div>
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Generated clips · {personaLabel(active)}</div>
          <div className="space-y-2">
            {(jobs ?? []).length === 0 && <p className="text-sm text-muted-foreground">Nothing yet. The first clip takes 1–4 minutes depending on the model.</p>}
            {(jobs ?? []).map(j => <JobCard key={j.id} job={j} onRetry={() => retry.mutate(j.id)} onDelete={async () => { if (await confirm({ title: "Delete this generated clip job?", subject: j.title, description: j.asset_id ? "The job record is removed; the clip already in the B-roll library stays." : "The job and its files are removed.", confirmLabel: "Delete job" })) del.mutate(j.id) }} onOpenAsset={() => nav("/assets")} />)}
          </div>
        </div>
      </div>
    </div>
  )
}

function JobCard({ job: j, onRetry, onDelete, onOpenAsset }: { job: AiBrollJob; onRetry: () => void; onDelete: () => void; onOpenAsset: () => void }) {
  const live = RUNNING.has(j.status)
  return (
    <Card className={cn(j.status === "FAILED" && "border-fail/40")}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-start justify-between gap-2 text-sm">
          <span className="min-w-0 truncate font-heading" title={j.title}>{j.title}</span>
          <span className={cn("shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider", j.status === "DONE" ? "bg-ready/15 text-ready" : j.status === "FAILED" ? "bg-fail/15 text-fail" : "bg-primary/15 text-primary")}>{j.status.toLowerCase()}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-xs">
        <div className="flex gap-3">
          <div className="relative aspect-[9/16] w-20 shrink-0 overflow-hidden rounded bg-surface-2">
            {j.video_url ? <video src={media.aibrollVideo(j.id)} muted loop playsInline autoPlay className="h-full w-full object-cover" /> : j.keyframe_url ? <img src={media.aibrollKeyframe(j.id)} alt="" className="h-full w-full object-cover" /> : <div className={cn("grid h-full place-items-center text-muted-foreground", live && "animate-pulse")}><Clapperboard className="size-4" /></div>}
            {j.use_reference && <span className="absolute left-1 top-1 rounded bg-background/80 px-1 font-mono text-[9px]">face</span>}
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="font-mono text-[11px] text-muted-foreground">{j.seconds}s · {j.video_provider} · {j.category} · {fmtDate(j.created_at)}</div>
            <p className="line-clamp-2 text-muted-foreground" title={j.prompt}>{j.prompt}</p>
            {live && <p className="text-primary">{j.stage_message}</p>}
            {j.status === "FAILED" && <p className="text-fail">{j.stage_message}</p>}
            {j.status === "DONE" && j.asset_id && <p className="flex items-center gap-1 text-ready"><Check className="size-3" /> in library as <span className="font-mono">{j.asset_id}</span></p>}
          </div>
        </div>
        <div className="flex justify-end gap-1">
          {j.status === "DONE" && <Button size="sm" variant="ghost" onClick={onOpenAsset}>Open B-roll</Button>}
          {j.status === "FAILED" && <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw className="size-3.5" /> Retry</Button>}
          {!live && <Button size="sm" variant="ghost" className="text-fail hover:text-fail" onClick={onDelete}><Trash2 className="size-3.5" /></Button>}
        </div>
      </CardContent>
    </Card>
  )
}

export function AiBrollLink({ itemId }: { itemId: string }) {
  return <Link to={`/ai-broll?item=${encodeURIComponent(itemId)}`} className="inline-flex items-center gap-1 text-primary hover:underline"><Sparkles className="size-3.5" /> Create with AI</Link>
}
