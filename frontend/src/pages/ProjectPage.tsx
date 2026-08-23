import { useEffect, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Check, ChevronLeft, ChevronRight, Download, RefreshCw, Repeat, Send, Shuffle, Type, Wand2 } from "lucide-react"
import { toast } from "sonner"
import { API, api, delivery, fmtDate, fmtTime, media } from "@/lib/api"
import type { Candidate, CaptionOverrides, Project } from "@/lib/types"
import { CaptionSettingsForm, applyCaptionOverrides } from "@/components/CaptionSettingsForm"
import { PageHeader } from "@/components/PageHeader"
import { StatusBadge } from "@/components/StatusBadge"
import { StageTimeline } from "@/components/StageTimeline"
import { SLIDESHOW_STAGES } from "@/lib/types"
import { Timeline } from "@/components/Timeline"
import { Thumb } from "@/components/Thumb"
import { Button, buttonVariants } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"

const RUNNING = new Set(["GENERATING_SCRIPT", "GENERATING_VOICE", "PLANNING", "SELECTING_ASSETS", "GENERATING_CAPTIONS", "RENDERING"])

export default function ProjectPage() {
  const { id = "" } = useParams()
  const qc = useQueryClient()
  const { data: p, isLoading } = useQuery({
    queryKey: ["project", id], queryFn: () => api.project(id),
    refetchInterval: q => (q.state.data && RUNNING.has(q.state.data.status) ? 2500 : false),
  })
  const running = !!p && RUNNING.has(p.status)
  const { data: plan } = useQuery({ queryKey: ["plan", id, p?.plan_version], queryFn: () => api.plan(id), enabled: !!p && p.plan_version > 0 })
  const { data: art } = useQuery({ queryKey: ["artifacts", id, p?.render_version, p?.script_version], queryFn: () => api.artifacts(id), enabled: !!p && !running })

  const videoRef = useRef<HTMLVideoElement>(null)
  const [t, setT] = useState(0)
  const [selScene, setSelScene] = useState<number | null>(null)
  const [changeScene, setChangeScene] = useState<number | null>(null)
  const [captionsOpen, setCaptionsOpen] = useState(false)
  useEffect(() => { setSelScene(null) }, [p?.plan_version])

  const refresh = () => { qc.invalidateQueries({ queryKey: ["project", id] }); qc.invalidateQueries({ queryKey: ["projects"] }) }
  const act = useMutation({
    mutationFn: (a: "generate" | "regenerate-script" | "change-assets" | "render" | "retry") => api.action(id, a),
    onSuccess: (_, a) => { toast.success(`${a.replace("-", " ")} started`); refresh() },
    onError: e => toast.error(e.message),
  })
  const approve = useMutation({ mutationFn: () => api.approve(id), onSuccess: () => { toast.success("Approved"); refresh() }, onError: e => toast.error(e.message) })
  const sendTg = useMutation({ mutationFn: () => delivery.sendTelegram(id), onSuccess: r => { toast.success(`Sent to Telegram (${r.sent.join(", ")})`); refresh() }, onError: e => toast.error(e.message) })
  const setAsset = useMutation({
    mutationFn: ({ order, asset_id }: { order: number; asset_id: string }) => api.setSceneAsset(id, order, asset_id),
    onSuccess: () => { toast.success("Re-rendering with the new clip"); setChangeScene(null); refresh() },
    onError: e => toast.error(e.message),
  })

  if (isLoading || !p) return <div className="p-8 text-muted-foreground">Loading…</div>
  const videoSrc = p.video_url ? `${media.video(id)}?v=${p.render_version}` : null

  return (
    <div>
      <PageHeader eyebrow={<Link to="/projects" className="inline-flex items-center gap-1 hover:text-foreground"><ArrowLeft className="size-3" /> Projects</Link> as unknown as string}
        title={p.topic}
        actions={<>
          <Button variant="outline" size="sm" disabled={running || p.script_version === 0} onClick={() => act.mutate("regenerate-script")} title="New hook + script → voice → scenes → render"><Wand2 className="size-4" /> Regenerate script</Button>
          <Button variant="outline" size="sm" disabled={running || p.plan_version === 0} onClick={() => act.mutate("change-assets")} title="Keep script & voice, pick different B-roll"><Shuffle className="size-4" /> Change assets</Button>
          <Button variant="outline" size="sm" disabled={running || p.plan_version === 0} onClick={() => act.mutate("render")} title="Same content, new visual variation"><Repeat className="size-4" /> Render again</Button>
          <Button variant="outline" size="sm" disabled={running} onClick={() => setCaptionsOpen(true)} title="Font & position of captions for this project"><Type className="size-4" /> Captions{p.caption_overrides ? " *" : ""}</Button>
          {p.status === "FAILED" && <Button variant="outline" size="sm" onClick={() => act.mutate("retry")}><RefreshCw className="size-4" /> Retry</Button>}
          {p.status === "DRAFT" && <Button size="sm" onClick={() => act.mutate("generate")}>Generate</Button>}
          {(p.status === "READY" || p.status === "APPROVED") && <Button variant="outline" size="sm" disabled={sendTg.isPending} onClick={() => sendTg.mutate()} title="Send the file to this persona's Telegram chat"><Send className="size-4" /> {sendTg.isPending ? "Sending…" : "Telegram"}</Button>}
          <Button size="sm" disabled={p.status !== "READY"} onClick={() => approve.mutate()}><Check className="size-4" /> {p.status === "APPROVED" ? "Approved" : "Approve"}</Button>
        </>}>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <StatusBadge status={p.status} />
          <span className="font-mono">{p.id}</span>
          <span className="font-mono">{p.template_id}</span>
          <span>{p.actual_duration ? `${p.actual_duration.toFixed(1)}s ${p.kind === "slideshow" ? "slideshow" : "voice"}` : `${p.target_duration}s target`}</span>
          <span className="font-mono">s{p.script_version} · v{p.voice_version} · p{p.plan_version} · r{p.render_version}</span>
          <span>{fmtDate(p.created_at)}</span>
        </div>
      </PageHeader>

      <div className="grid gap-6 px-8 py-6 xl:grid-cols-[320px_1fr]">
        {/* player */}
        <div className="space-y-3">
          <div className="aspect-[9/16] w-full overflow-hidden rounded-lg border border-border bg-black">
            {p.kind === "slideshow" ? (<SlideGallery p={p} />) : videoSrc ? (
              <video key={videoSrc} ref={videoRef} src={videoSrc} controls playsInline className="h-full w-full"
                onTimeUpdate={e => setT(e.currentTarget.currentTime)} />
            ) : (
              <div className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">
                {running ? "Rendering… the preview appears here when it’s ready." : p.status === "FAILED" ? "No render — fix the error and retry." : "No render yet."}
              </div>
            )}
          </div>
          {videoSrc && (
            <div className="flex gap-2">
              <a href={videoSrc} download={`${p.id}.mp4`} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "flex-1")}><Download className="size-4" /> Download MP4</a>
            </div>
          )}
          {p.voice_version > 0 && p.kind !== "slideshow" && (
            <div>
              <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Voice v{p.voice_version}</div>
              <audio key={p.voice_version} src={`${media.voice(id)}?v=${p.voice_version}`} controls className="w-full" />
            </div>
          )}
        </div>

        {/* right column */}
        <div className="min-w-0 space-y-6">
          <StageTimeline stages={p.kind === "slideshow" ? SLIDESHOW_STAGES : undefined} status={p.status} error={p.error} message={p.stage_message} />

          {plan && (
            <section>
              <div className="mb-2 flex items-baseline justify-between">
                <h2 className="font-heading text-sm font-semibold">Timeline · plan v{p.plan_version}</h2>
                <span className="font-mono text-[11px] text-muted-foreground">{plan.scenes.length} scenes · {plan.captions.length} caption chunks · seed {plan.seed} · {fmtTime(t)} / {fmtTime(plan.scenes[plan.scenes.length - 1].end)}</span>
              </div>
              <Timeline plan={plan} currentTime={t} selectedScene={selScene}
                onSeek={s => { if (videoRef.current) { videoRef.current.currentTime = s; setT(s) } }}
                onSceneClick={o => setSelScene(o)} />
            </section>
          )}

          <Tabs defaultValue="scenes">
            <TabsList>
              <TabsTrigger value="scenes">Scenes</TabsTrigger>
              <TabsTrigger value="script">Script</TabsTrigger>
              <TabsTrigger value="renders">Renders</TabsTrigger>
              <TabsTrigger value="events">Log</TabsTrigger>
              <TabsTrigger value="json">Video JSON</TabsTrigger>
            </TabsList>

            <TabsContent value="scenes" className="pt-3">
              {p.scenes.length === 0 ? <p className="text-sm text-muted-foreground">Scenes appear after planning.</p> : (
                <ul className="divide-y divide-border rounded-md border border-border">
                  {p.scenes.map(s => (
                    <li key={s.order} className={cn("flex items-center gap-3 p-2", selScene === s.order && "bg-primary/5")}
                      onMouseEnter={() => setSelScene(s.order)}>
                      {s.asset_id && <Thumb assetId={s.asset_id} className="w-12 shrink-0" />}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                          <span className="text-foreground">{p.kind === "slideshow" ? `SLIDE ${s.order + 1}` : `SCENE ${s.order}`}</span>{p.kind !== "slideshow" && <span>{fmtTime(s.start_time)}–{fmtTime(s.end_time)}</span>}
                          {p.kind !== "slideshow" && <span>{(s.end_time - s.start_time).toFixed(1)}s</span>}<span className="uppercase">{s.section}</span>
                          <span>{s.asset_id}{p.kind !== "slideshow" ? ` @ ${s.asset_start_time.toFixed(2)}s` : ""}</span>
                        </div>
                        <div className="truncate text-sm" title={s.intent ?? ""}>{s.intent}</div>
                        {s.overlay_text && <div className="font-mono text-[11px] text-primary">overlay “{s.overlay_text}”</div>}
                      </div>
                      <Button variant="outline" size="sm" disabled={running} onClick={() => setChangeScene(s.order)}>Change</Button>
                    </li>
                  ))}
                </ul>
              )}
            </TabsContent>

            <TabsContent value="script" className="pt-3">
              {art?.scripts.length ? (
                <div className="space-y-4">
                  {[...art.scripts].reverse().map(s => (
                    <div key={s.version} className="rounded-md border border-border p-4">
                      <div className="mb-2 font-mono text-[11px] text-muted-foreground">script v{s.version}{s.version === p.script_version ? " · current" : ""}</div>
                      <ol className="space-y-1.5">
                        {s.content.sections.map(sec => (
                          <li key={sec.type} className="flex gap-3 text-sm"><span className="w-24 shrink-0 font-mono text-[11px] uppercase text-primary">{sec.type}</span><span>{sec.text}</span></li>
                        ))}
                      </ol>
                    </div>
                  ))}
                </div>
              ) : <p className="text-sm text-muted-foreground">{p.script ?? "No script yet."}</p>}
            </TabsContent>

            <TabsContent value="renders" className="pt-3">
              {p.renders.length === 0 ? <p className="text-sm text-muted-foreground">No renders yet.</p> : (
                <ul className="space-y-2">
                  {[...p.renders].reverse().map(r => (
                    <li key={r.id} className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3 text-sm">
                      <span className="font-mono">render v{r.version}</span>
                      <span className={cn("rounded px-1.5 font-mono text-[11px]", r.status === "DONE" ? "bg-ready/15 text-ready" : "bg-fail/15 text-fail")}>{r.status}</span>
                      <span className="font-mono text-[11px] text-muted-foreground">plan p{r.plan_version} · voice v{r.voice_version}</span>
                      {r.qc && <span className="font-mono text-[11px] text-muted-foreground">QC {r.qc.passed ? "passed" : `failed: ${r.qc.failures.join("; ")}`}{r.qc.info?.duration ? ` · ${Number(r.qc.info.duration).toFixed(1)}s` : ""}</span>}
                      {r.error && <span className="text-xs text-fail">{r.error}</span>}
                      <span className="ml-auto text-xs text-muted-foreground">{fmtDate(r.created_at)}</span>
                      {r.status === "DONE" && <a className="text-xs text-primary underline" href={media.renderVideo(id, r.version)} target="_blank" rel="noreferrer">open</a>}
                    </li>
                  ))}
                </ul>
              )}
            </TabsContent>

            <TabsContent value="events" className="pt-3">
              <ul className="max-h-[420px] space-y-1 overflow-auto rounded-md border border-border p-3 font-mono text-[11px]">
                {[...p.events].reverse().map((e, i) => (
                  <li key={i} className={cn("flex gap-3", e.level === "error" && "text-fail", e.level === "warning" && "text-primary")}>
                    <span className="shrink-0 text-muted-foreground">{new Date(e.created_at).toLocaleTimeString()}</span>
                    <span className="w-28 shrink-0 uppercase text-muted-foreground">{e.stage}</span><span className="break-all">{e.message}</span>
                  </li>
                ))}
              </ul>
            </TabsContent>

            <TabsContent value="json" className="pt-3">
              <pre className="max-h-[520px] overflow-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-[11px] leading-relaxed">{plan ? JSON.stringify(plan, null, 2) : "No plan yet."}</pre>
            </TabsContent>
          </Tabs>
        </div>
      </div>

      <ChangeSceneDialog project={p} order={changeScene} onClose={() => setChangeScene(null)}
        onPick={(asset_id) => changeScene != null && setAsset.mutate({ order: changeScene, asset_id })} busy={setAsset.isPending} />
      <ProjectCaptionsDialog project={p} open={captionsOpen} onClose={() => setCaptionsOpen(false)}
        onSaved={(render) => { refresh(); if (render) act.mutate("render") }} />
    </div>
  )
}

/** Per-project caption overrides on top of the system settings. Saved values apply on the next render. */
function ProjectCaptionsDialog({ project, open, onClose, onSaved }: { project: Project; open: boolean; onClose: () => void; onSaved: (render: boolean) => void }) {
  const { data: sys } = useQuery({ queryKey: ["caption-settings"], queryFn: api.captionSettings, enabled: open })
  const [ov, setOv] = useState<CaptionOverrides>(project.caption_overrides ?? {})
  useEffect(() => { if (open) setOv(project.caption_overrides ?? {}) }, [open, project.caption_overrides])
  // base for this project = template style (+ global settings); caption_style from the API already includes the project overrides,
  // so rebuild the base from the system defaults + global overrides when available
  const base = sys ? applyCaptionOverrides({ ...sys.defaults, ...(project.caption_style ? { safe_zone: project.caption_style.safe_zone } : {}) }, sys.overrides) : project.caption_style
  const save = useMutation({
    mutationFn: (render: boolean) => api.setProjectCaptions(project.id, Object.values(ov).some(v => v != null) ? ov : null).then(() => render),
    onSuccess: render => { toast.success(render ? "Caption settings saved — rendering again" : "Caption settings saved — use Render again to apply"); onSaved(render); onClose() },
    onError: e => toast.error(e.message),
  })
  const hasOverrides = Object.values(ov).some(v => v != null)
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="font-heading">Captions · this project</DialogTitle>
          <DialogDescription>Font and position overrides for <span className="font-mono">{project.id}</span> only. Empty fields use the system settings (System → Captions). Changes apply when the project is rendered again.</DialogDescription>
        </DialogHeader>
        {base ? <CaptionSettingsForm base={base} value={ov} onChange={setOv} scopeLabel="system setting" /> : <p className="text-sm text-muted-foreground">Loading…</p>}
        <div className="flex items-center justify-between border-t border-border pt-4">
          <Button type="button" variant="ghost" disabled={!hasOverrides} onClick={() => setOv({})}>Use system settings</Button>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="button" variant="outline" disabled={save.isPending} onClick={() => save.mutate(false)}>Save</Button>
            <Button type="button" disabled={save.isPending || project.plan_version === 0} onClick={() => save.mutate(true)}><Repeat className="size-4" /> Save &amp; render again</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ChangeSceneDialog({ project, order, onClose, onPick, busy }: { project: Project; order: number | null; onClose: () => void; onPick: (id: string) => void; busy: boolean }) {
  const scene = project.scenes.find(s => s.order === order)
  const { data, isLoading } = useQuery({ queryKey: ["suggest", project.id, order, project.plan_version], queryFn: () => api.suggestions(project.id, order!), enabled: order != null })
  return (
    <Dialog open={order != null} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="font-heading">Change B-roll · scene {order}</DialogTitle>
          <DialogDescription>{scene?.intent} <span className="font-mono text-[11px]">(current {scene?.asset_id})</span></DialogDescription>
        </DialogHeader>
        {isLoading && <p className="text-sm text-muted-foreground">Finding clips…</p>}
        <div className="grid max-h-[60vh] grid-cols-2 gap-3 overflow-auto sm:grid-cols-4">
          {(data ?? []).map((c: Candidate) => (
            <button key={c.asset_id} type="button" disabled={busy} onClick={() => onPick(c.asset_id)}
              className="group rounded-md border border-border p-1.5 text-left hover:border-primary focus-visible:outline-2 focus-visible:outline-ring">
              <Thumb assetId={c.asset_id} />
              <div className="mt-1 flex items-center justify-between font-mono text-[11px]"><span>{c.asset_id}</span><span className="text-muted-foreground">{c.duration.toFixed(1)}s</span></div>
              <div className="line-clamp-2 text-[11px] text-muted-foreground">{c.description}</div>
              {c.recently_used && <div className="font-mono text-[10px] text-primary">used recently</div>}
            </button>
          ))}
        </div>
        {!isLoading && data?.length === 0 && <p className="text-sm text-muted-foreground">No alternative clips available.</p>}
      </DialogContent>
    </Dialog>
  )
}

/** TikTok photo-mode output: one slide at a time with ← → (like the TikTok carousel), zip download, suggested caption. */
function SlideGallery({ p }: { p: Project }) {
  const slides = p.slides ?? []
  const running = RUNNING.has(p.status)
  const [i, setI] = useState(0)
  const [touchX, setTouchX] = useState<number | null>(null)
  useEffect(() => { setI(0) }, [p.render_version, slides.length])
  const n = slides.length
  const go = (d: number) => { if (n) setI(x => (x + d + n) % n) }
  if (!n) {
    return <div className="grid aspect-[9/16] w-full place-items-center rounded-md border border-border bg-black/60 p-6 text-center text-sm text-muted-foreground">{running ? "Rendering the slides… they appear here when ready." : p.status === "FAILED" ? "No slides — fix the error and retry." : "No slides yet."}</div>
  }
  return (
    <div className="space-y-2">
      <div className="relative overflow-hidden rounded-md border border-border bg-black" tabIndex={0}
        onKeyDown={e => { if (e.key === "ArrowLeft") go(-1); if (e.key === "ArrowRight") go(1) }}
        onTouchStart={e => setTouchX(e.touches[0].clientX)}
        onTouchEnd={e => { if (touchX != null) { const dx = e.changedTouches[0].clientX - touchX; if (Math.abs(dx) > 40) go(dx < 0 ? 1 : -1) } setTouchX(null) }}>
        <img key={slides[i]} src={`${API}${slides[i]}`} alt={`slide ${i + 1}`} className="aspect-[9/16] w-full object-cover" />
        <button type="button" aria-label="Previous slide" onClick={() => go(-1)} className="absolute left-2 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full bg-background/70 text-foreground shadow hover:bg-background focus-visible:outline-2 focus-visible:outline-ring"><ChevronLeft className="size-5" /></button>
        <button type="button" aria-label="Next slide" onClick={() => go(1)} className="absolute right-2 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-full bg-background/70 text-foreground shadow hover:bg-background focus-visible:outline-2 focus-visible:outline-ring"><ChevronRight className="size-5" /></button>
        <span className="absolute left-2 top-2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-[11px]">{i + 1}/{n}</span>
        <a href={`${API}${slides[i]}`} target="_blank" rel="noreferrer" className="absolute right-2 top-2 rounded bg-background/80 px-1.5 py-0.5 font-mono text-[11px] hover:bg-background">open</a>
        <div className="absolute inset-x-0 bottom-2 flex justify-center gap-1">
          {slides.map((_, k) => <button key={k} type="button" aria-label={`slide ${k + 1}`} onClick={() => setI(k)} className={cn("h-1.5 rounded-full transition-all", k === i ? "w-5 bg-primary" : "w-1.5 bg-foreground/50 hover:bg-foreground")} />)}
        </div>
      </div>
      <div className="flex gap-1 overflow-x-auto pb-1">
        {slides.map((u, k) => <button key={u} type="button" onClick={() => setI(k)} className={cn("shrink-0 overflow-hidden rounded border", k === i ? "border-primary" : "border-border opacity-70 hover:opacity-100")}><img src={`${API}${u}`} alt="" loading="lazy" className="h-16 w-9 object-cover" /></button>)}
      </div>
      {p.slides_zip_url && <a href={`${API}${p.slides_zip_url}`} className={cn(buttonVariants({ variant: "outline", size: "sm" }), "w-full")}><Download className="size-4" /> Download all slides (zip)</a>}
      {p.post_caption && <div className="rounded-md border border-border bg-card p-2 text-xs"><span className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">post caption</span><p className="mt-1">{p.post_caption}</p><p className="mt-1 text-[11px] text-muted-foreground">Upload the images as a photo post on TikTok and pick a trending sound there.</p></div>}
    </div>
  )
}
