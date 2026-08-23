import { useState } from "react"
import { useParams, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Clapperboard, Copy, Download, ExternalLink, Images, RefreshCw } from "lucide-react"
import { API, delivery, fmtDate } from "@/lib/api"
import type { InboxItem } from "@/lib/types"
import { cn } from "@/lib/utils"

/**
 * Phone-friendly inbox for one persona: approved videos / slideshows, ready to save to the camera roll and post.
 * Opened from a token link (QR on the Personas page); no app login, no sidebar.
 */
export default function InboxPage() {
  const { persona = "" } = useParams()
  const [params] = useSearchParams()
  const key = params.get("key") ?? ""
  const [all, setAll] = useState(false)
  const { data, error, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["inbox", persona, key, all], queryFn: () => delivery.inboxItems(persona, key, !all), enabled: !!persona && !!key, refetchInterval: 30_000,
  })
  return (
    <div className="mx-auto min-h-screen max-w-md bg-background px-4 pb-16 pt-5 text-foreground">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">ClipFactory inbox</div>
          <h1 className="font-heading text-xl font-bold">{data?.persona_name ?? persona}</h1>
        </div>
        <button type="button" onClick={() => refetch()} className="rounded-md border border-border p-2 text-muted-foreground hover:text-foreground" aria-label="Refresh"><RefreshCw className={cn("size-4", isFetching && "animate-spin")} /></button>
      </header>
      {!key && <p className="text-sm text-fail">This link has no key. Scan the QR code on the Personas page again.</p>}
      {error && <p className="text-sm text-fail">{String((error as Error).message)} — ask for a new inbox link.</p>}
      <label className="mb-3 flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" className="scrub size-3.5" checked={all} onChange={e => setAll(e.target.checked)} /> also show videos that are ready but not approved yet</label>
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {data && data.items.length === 0 && <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">Nothing to post yet. Approve a video on the computer and it shows up here.</p>}
      <div className="space-y-4">
        {data?.items.map(it => <InboxCard key={it.id} it={it} />)}
      </div>
      <p className="mt-8 text-center text-[11px] text-muted-foreground">Save to Photos: open the video/image, then long-press (iPhone: Share → Save Video / Save Image). Zip: open in Files → Save images.</p>
    </div>
  )
}

function InboxCard({ it }: { it: InboxItem }) {
  const [copied, setCopied] = useState(false)
  const copy = async (t: string) => { try { await navigator.clipboard.writeText(t); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* ignore */ } }
  return (
    <article className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-start justify-between gap-2 px-3 pt-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{it.topic}</div>
          <div className="font-mono text-[11px] text-muted-foreground">{it.kind === "slideshow" ? `${it.slides.length} slides` : it.duration ? `${it.duration.toFixed(0)}s video` : "video"} · {fmtDate(it.approved_at ?? it.created_at)}{it.status !== "APPROVED" ? " · not approved" : ""}</div>
        </div>
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase", it.kind === "slideshow" ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground")}>{it.kind}</span>
      </div>
      {it.kind === "video" && it.video_url && (
        <div className="p-3">
          <video src={`${API}${it.video_url}`} controls playsInline preload="metadata" className="aspect-[9/16] w-full rounded-md bg-black" />
          <a href={`${API}${it.video_url}`} target="_blank" rel="noreferrer" className="mt-2 flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"><Download className="size-4" /> Open video to save</a>
        </div>
      )}
      {it.kind === "slideshow" && (
        <div className="p-3">
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            {it.slides.map((u, i) => <a key={u} href={`${API}${u}`} target="_blank" rel="noreferrer" className="relative shrink-0 overflow-hidden rounded border border-border"><img src={`${API}${u}`} alt={`slide ${i + 1}`} loading="lazy" className="h-40 w-[90px] object-cover" /><span className="absolute left-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">{i + 1}</span></a>)}
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground"><Images className="mr-1 inline size-3" /> Tap a slide to open it full size, then save it; repeat for each (TikTok photo post order = 1…{it.slides.length}).</p>
          {it.zip_url && <a href={`${API}${it.zip_url}`} className="mt-2 flex items-center justify-center gap-2 rounded-md border border-border px-3 py-2 text-sm"><Download className="size-4" /> Download all (zip)</a>}
          {it.post_caption && (
            <div className="mt-2 rounded-md border border-border bg-background p-2 text-xs">
              <div className="mb-1 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.18em] text-primary">caption <button type="button" onClick={() => copy(it.post_caption!)} className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"><Copy className="size-3" /> {copied ? "copied" : "copy"}</button></div>
              <p>{it.post_caption}</p>
            </div>
          )}
        </div>
      )}
      {it.kind === "video" && !it.video_url && <p className="flex items-center gap-2 p-3 text-xs text-muted-foreground"><Clapperboard className="size-4" /> no render yet <ExternalLink className="size-3" /></p>}
    </article>
  )
}
