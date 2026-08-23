import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronRight, Clapperboard, ExternalLink, Lightbulb, Link2, RefreshCw, Sparkles, Trash2, TrendingUp, Wand2 } from "lucide-react"
import { toast } from "sonner"
import { fmtDate, media, trends } from "@/lib/api"
import { personaLabel, usePersona } from "@/lib/persona"
import type { Template, Trend } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { TemplateEditor } from "@/components/TemplateEditor"
import { useConfirm } from "@/components/ConfirmDialog"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

const RUNNING = new Set(["QUEUED", "DOWNLOADING", "TRANSCRIBING", "ANALYZING"])

/** Paste a TikTok / Reels / Shorts link → the video is fetched, transcribed and reverse-engineered for the active persona. */
export default function TrendsPage() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const confirm = useConfirm()
  const { activeId, active } = usePersona()
  const [url, setUrl] = useState("")
  const [sel, setSel] = useState<string | null>(null)
  const { data: list } = useQuery({
    queryKey: ["trends", activeId], queryFn: () => trends.list(activeId || undefined), enabled: !!activeId,
    refetchInterval: q => (q.state.data?.some(t => RUNNING.has(t.status)) ? 3000 : false),
  })
  useEffect(() => { if (!sel && list?.length) setSel(list[0].id) }, [list, sel])
  const { data: detail } = useQuery({
    queryKey: ["trend", sel], queryFn: () => trends.get(sel!), enabled: !!sel,
    refetchInterval: q => (q.state.data && RUNNING.has(q.state.data.status) ? 3000 : false),
  })
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["trends"] }); qc.invalidateQueries({ queryKey: ["trend"] }) }
  const create = useMutation({
    mutationFn: () => trends.create({ url: url.trim(), persona_id: activeId || null }),
    onSuccess: t => { toast.success("Analysing — this takes ~1 minute"); setUrl(""); setSel(t.id); invalidate() },
    onError: e => toast.error(e.message),
  })
  const retry = useMutation({ mutationFn: trends.retry, onSuccess: () => { toast.success("Retrying"); invalidate() }, onError: e => toast.error(e.message) })
  const del = useMutation({ mutationFn: trends.delete, onSuccess: () => { toast.success("Deleted"); setSel(null); invalidate() }, onError: e => toast.error(e.message) })
  const valid = /^https?:\/\/\S+$/.test(url.trim())

  return (
    <div>
      <PageHeader eyebrow="What's working" title="Trends">
        <p className="mt-1 text-sm text-muted-foreground">Paste a TikTok, Reels or Shorts link. The video is fetched, transcribed and broken down — hook, structure, pacing, captions, why it works — then translated into tips and remix ideas for <span className="text-foreground">{personaLabel(active)}</span>. Like it? Turn it into a template with one click.</p>
      </PageHeader>
      <div className="px-8 py-4">
        <form noValidate className="flex gap-2" onSubmit={e => { e.preventDefault(); if (valid) create.mutate() }}>
          <div className="relative flex-1"><Link2 className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><Input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.tiktok.com/@creator/video/… or https://www.instagram.com/reel/…" className="h-11 pl-9 text-base" /></div>
          <Button type="submit" size="lg" disabled={!valid || create.isPending}><TrendingUp className="size-4" /> {create.isPending ? "Starting…" : "Analyse"}</Button>
        </form>
        <p className="mt-1 text-[11px] text-muted-foreground">Public videos only (yt-dlp). The copy stays on your machine for the preview; you are responsible for the platforms' terms. Instagram sometimes needs a logged-in browser — if it fails, try the TikTok/YouTube link of the same video.</p>
      </div>
      <div className="grid gap-6 px-8 pb-10 xl:grid-cols-[360px_1fr]">
        <div className="space-y-2">
          {(list ?? []).length === 0 && <p className="text-sm text-muted-foreground">No analyses yet.</p>}
          {(list ?? []).map(t => (
            <button key={t.id} type="button" onClick={() => setSel(t.id)} className={cn("flex w-full gap-3 rounded-md border bg-card p-2 text-left transition-colors hover:border-primary/60", sel === t.id ? "border-primary" : "border-border")}>
              <div className="relative aspect-[9/16] w-14 shrink-0 overflow-hidden rounded bg-surface-2">
                {t.thumbnail_url ? <img src={media.trendThumb(t.id)} alt="" className="h-full w-full object-cover" /> : <div className={cn("grid h-full place-items-center text-muted-foreground", RUNNING.has(t.status) && "animate-pulse")}><Clapperboard className="size-4" /></div>}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{t.title || t.url}</div>
                <div className="font-mono text-[11px] text-muted-foreground">{t.platform}{t.uploader ? ` · ${t.uploader}` : ""}{t.duration ? ` · ${t.duration.toFixed(0)}s` : ""} · {fmtDate(t.created_at)}</div>
                <div className={cn("mt-1 inline-block rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider", t.status === "DONE" ? "bg-ready/15 text-ready" : t.status === "FAILED" ? "bg-fail/15 text-fail" : "bg-primary/15 text-primary")}>{t.status.toLowerCase()}</div>
                {t.template_id && <span className="ml-2 font-mono text-[10px] text-muted-foreground">→ {t.template_id}</span>}
              </div>
            </button>
          ))}
        </div>
        <div>
          {detail ? <TrendDetail t={detail} onRetry={() => retry.mutate(detail.id)} onDelete={async () => { if (await confirm({ title: "Delete this analysis?", subject: detail.title ?? detail.url, description: "The downloaded copy and the analysis are removed. Templates already created from it stay.", confirmLabel: "Delete analysis" })) del.mutate(detail.id) }} onTemplateCreated={tpl => { invalidate(); nav(`/generate?template=${encodeURIComponent(tpl.id)}`) }} /> : <p className="text-sm text-muted-foreground">Select an analysis, or paste a link above.</p>}
        </div>
      </div>
    </div>
  )
}

function TrendDetail({ t, onRetry, onDelete, onTemplateCreated }: { t: Trend; onRetry: () => void; onDelete: () => void; onTemplateCreated: (tpl: Template) => void }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { activeId } = usePersona()
  const [editing, setEditing] = useState(false)
  const [genTopic, setGenTopic] = useState<string | null>(null)  // null = dialog closed
  const [genLen, setGenLen] = useState(18)
  const gen = useMutation({
    mutationFn: () => trends.generate(t.id, { topic: (genTopic ?? "").trim(), persona_id: t.persona_id ?? activeId, target_duration: genLen }),
    onSuccess: p => { toast.success("Video started with this trend's structure"); qc.invalidateQueries({ queryKey: ["projects"] }); setGenTopic(null); nav(`/projects/${p.id}`) },
    onError: e => toast.error(e.message),
  })
  const openGen = (topic?: string) => { setGenTopic(topic ?? t.analysis?.remix_ideas?.[0] ?? ""); setGenLen(Math.round(Math.min(25, Math.max(15, t.analysis?.template_proposal?.duration_target ?? 18)))) }
  const [showTranscript, setShowTranscript] = useState(false)
  const a = t.analysis
  const live = RUNNING.has(t.status)
  const dur = t.duration || (a ? Math.max(...a.structure.map(s => s.end)) : 0)
  const draft = useMemo<Template | null>(() => (t.template_draft ? { ...t.template_draft } : null), [t.template_draft])
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-4">
        <div className="relative aspect-[9/16] w-36 shrink-0 overflow-hidden rounded-md border border-border bg-surface-2">
          {t.video_url ? <video src={media.trendVideo(t.id)} controls muted playsInline className="h-full w-full object-cover" poster={t.thumbnail_url ? media.trendThumb(t.id) : undefined} /> : <div className={cn("grid h-full place-items-center text-muted-foreground", live && "animate-pulse")}><Clapperboard className="size-5" /></div>}
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="font-heading text-xl font-semibold leading-tight">{t.title || "Untitled"}</h2>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">{t.platform}{t.uploader ? ` · ${t.uploader}` : ""}{t.duration ? ` · ${t.duration.toFixed(1)}s` : ""}{t.meta.view_count ? ` · ${Intl.NumberFormat().format(t.meta.view_count)} views` : ""}{t.meta.like_count ? ` · ${Intl.NumberFormat().format(t.meta.like_count)} likes` : ""} · <a href={t.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-foreground">source <ExternalLink className="size-3" /></a></p>
          {live && <p className="mt-2 text-sm text-primary">{t.stage_message}</p>}
          {t.status === "FAILED" && <p className="mt-2 text-sm text-fail">{t.stage_message}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            {a && <Button size="sm" onClick={() => openGen()}><Sparkles className="size-3.5" /> Generate a video from this</Button>}
            {a && !t.template_id && <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Wand2 className="size-3.5" /> Create template from this</Button>}
            {t.template_id && <Button size="sm" variant="outline" onClick={() => nav(`/generate?template=${encodeURIComponent(t.template_id!)}`)}><Sparkles className="size-3.5" /> Generate with {t.template_id}</Button>}
            {t.status === "FAILED" && <Button size="sm" variant="outline" onClick={onRetry}><RefreshCw className="size-3.5" /> Retry</Button>}
            {t.has_transcript && <Button size="sm" variant="ghost" onClick={() => setShowTranscript(s => !s)}>{showTranscript ? "Hide" : "Show"} transcript</Button>}
            {!live && <Button size="sm" variant="ghost" className="text-fail hover:text-fail" onClick={onDelete}><Trash2 className="size-3.5" /></Button>}
          </div>
        </div>
      </div>
      {showTranscript && t.transcript && <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-surface-2 p-3 text-xs leading-relaxed">{t.transcript}</pre>}

      {a && (
        <div className="space-y-5">
          <p className="text-sm">{a.summary}</p>
          <Block title="Hook" accent>
            <p className="font-heading text-lg">“{a.hook.text}”</p>
            <p className="font-mono text-[11px] text-muted-foreground">{a.hook.type} · first {a.hook.seconds}s</p>
          </Block>
          <Block title="Structure">
            <div className="flex h-7 w-full overflow-hidden rounded border border-border">
              {a.structure.map((s, i) => <div key={i} title={`${s.label} ${s.start}–${s.end}s: ${s.purpose}`} style={{ width: `${dur ? ((s.end - s.start) / dur) * 100 : 100 / a.structure.length}%` }} className={cn("flex items-center justify-center truncate px-1 font-mono text-[10px]", i % 2 ? "bg-primary/25" : "bg-primary/50")}>{s.label}</div>)}
            </div>
            <ol className="mt-2 space-y-1 text-sm">{a.structure.map((s, i) => <li key={i} className="flex gap-2"><span className="w-24 shrink-0 font-mono text-[11px] text-primary">{s.label}</span><span className="w-20 shrink-0 font-mono text-[11px] text-muted-foreground">{s.start}–{s.end}s</span><span className="text-muted-foreground">{s.purpose}</span></li>)}</ol>
          </Block>
          <div className="grid gap-3 md:grid-cols-2">
            <Block title="Pacing"><p className="text-sm text-muted-foreground">{a.pacing}</p></Block>
            <Block title="Visual style"><p className="text-sm text-muted-foreground">{a.visual_style}</p></Block>
            <Block title="Captions / text"><p className="text-sm text-muted-foreground">{a.caption_style}</p></Block>
            <Block title="Audio"><p className="text-sm text-muted-foreground">{a.audio}</p></Block>
          </div>
          <Block title="Why it works"><ul className="list-disc space-y-1 pl-5 text-sm">{a.why_it_works.map((x, i) => <li key={i}>{x}</li>)}</ul></Block>
          <Block title={`Tips for ${t.persona_id ?? "you"}`} accent><ul className="space-y-1.5 text-sm">{a.tips_for_persona.map((x, i) => <li key={i} className="flex gap-2"><Lightbulb className="mt-0.5 size-4 shrink-0 text-primary" />{x}</li>)}</ul></Block>
          <Block title="Remix ideas (hooks you could shoot)">
            <ul className="space-y-1 text-sm">{a.remix_ideas.map((x, i) => <li key={i} className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1"><span>{x}</span><button type="button" className="inline-flex shrink-0 items-center gap-1 font-mono text-[11px] text-primary hover:underline" onClick={() => openGen(x)}>generate <ChevronRight className="size-3" /></button></li>)}</ul>
          </Block>
          <Block title="Template proposal">
            <p className="text-sm"><span className="font-heading font-semibold">{a.template_proposal.name}</span> <span className="font-mono text-[11px] text-muted-foreground">{a.template_proposal.id}</span></p>
            <p className="text-sm text-muted-foreground">{a.template_proposal.description}</p>
            <p className="mt-1 font-mono text-[11px] text-muted-foreground">{a.template_proposal.duration_min}–{a.template_proposal.duration_max}s (target {a.template_proposal.duration_target}) · shots {a.template_proposal.shot_min}–{a.template_proposal.shot_max}s · overlays {a.template_proposal.overlays_min}–{a.template_proposal.overlays_max} · {a.template_proposal.voiceover ? "voice-over" : "no voice-over"}</p>
            <p className="mt-1 text-xs"><span className="font-mono text-primary">closing</span> <span className="text-muted-foreground">{a.template_proposal.closing}</span></p>
            <p className="mt-2 text-xs text-muted-foreground">Not every trend deserves a template: <b>Generate a video from this</b> uses this structure once, for a single project; <b>Create template</b> saves it for reuse.</p>
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={() => openGen()}><Sparkles className="size-3.5" /> Generate a video from this</Button>
              {!t.template_id ? <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Wand2 className="size-3.5" /> Review & create template</Button> : <p className="self-center text-xs text-ready">Template created: <span className="font-mono">{t.template_id}</span></p>}
            </div>
          </Block>
        </div>
      )}
      <Dialog open={genTopic !== null} onOpenChange={o => { if (!o && !gen.isPending) setGenTopic(null) }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-heading">Generate a video with this structure</DialogTitle>
            <DialogDescription>One-off: the project uses this trend's sections, pacing and closing rule without saving a template. Script, voice, B-roll and render run as usual.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="gen-topic" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Topic</Label>
              <Textarea id="gen-topic" rows={3} value={genTopic ?? ""} onChange={e => setGenTopic(e.target.value)} placeholder="Write it the way the hook could sound" />
              {a && a.remix_ideas.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{a.remix_ideas.slice(0, 6).map((x, i) => <button key={i} type="button" onClick={() => setGenTopic(x)} className={cn("rounded-md border px-2 py-0.5 text-left text-[11px]", genTopic === x ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{x}</button>)}</div>}
            </div>
            <div>
              <Label htmlFor="gen-len" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Target length · <span className="font-mono text-foreground">{genLen}s</span></Label>
              <input id="gen-len" type="range" min={15} max={25} step={1} value={genLen} onChange={e => setGenLen(Number(e.target.value))} className="scrub w-full" />
            </div>
          </div>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button type="button" variant="outline" onClick={() => setGenTopic(null)} disabled={gen.isPending}>Cancel</Button>
            <Button type="button" onClick={() => gen.mutate()} disabled={gen.isPending || (genTopic ?? "").trim().length < 3}><Sparkles className="size-4" /> {gen.isPending ? "Starting…" : "Generate video"}</Button>
          </div>
        </DialogContent>
      </Dialog>
      <TemplateEditor template={editing ? "new" : null} initial={draft} onClose={() => setEditing(false)} onSaved={async tpl => { try { await trends.createTemplate(t.id, tpl) } catch { /* the template itself was saved by the editor; linking is best-effort */ } onTemplateCreated(tpl) }} />
    </div>
  )
}

function Block({ title, accent, children }: { title: string; accent?: boolean; children: React.ReactNode }) {
  return (
    <section className={cn("rounded-md border p-3", accent ? "border-primary/40 bg-primary/5" : "border-border bg-card")}>
      <h3 className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-primary">{title}</h3>
      {children}
    </section>
  )
}
