import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Layers, Play, Square, X } from "lucide-react"
import { toast } from "sonner"
import { api, fmtDate } from "@/lib/api"
import type { Batch } from "@/lib/types"
import { usePersona } from "@/lib/persona"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

const ACTIVE = new Set(["PENDING", "RUNNING"])
const MAX = 60

/** Start a batch: how many videos, which templates, AI topics or your own. */
export function BatchDialog({ open, onClose, onStarted }: { open: boolean; onClose: () => void; onStarted: (b: Batch) => void }) {
  const { activeId, active } = usePersona()
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: api.templates })
  const [count, setCount] = useState(10)
  const [tids, setTids] = useState<string[]>([])
  const [duration, setDuration] = useState(18)
  const [topicsMode, setTopicsMode] = useState<"ai" | "own">("ai")
  const [own, setOwn] = useState("")
  const [name, setName] = useState("")
  useEffect(() => { if (open) { setCount(10); setTids(templates?.map(t => t.id) ?? []); setDuration(18); setTopicsMode("ai"); setOwn(""); setName("") } }, [open, templates])
  const ownTopics = useMemo(() => own.split("\n").map(s => s.trim()).filter(Boolean), [own])
  const effectiveCount = topicsMode === "own" ? ownTopics.length : count
  const start = useMutation({
    mutationFn: () => api.createBatch({
      persona_id: activeId, count: Math.max(1, Math.min(MAX, effectiveCount)), template_ids: tids.length ? tids : null,
      topics: topicsMode === "own" ? ownTopics : null, target_duration: duration, name: name.trim() || null,
    }),
    onSuccess: b => { toast.success(`Batch started — ${b.total} videos queued`); onStarted(b); onClose() },
    onError: e => toast.error(e.message),
  })
  const toggle = (id: string) => setTids(x => x.includes(id) ? x.filter(t => t !== id) : [...x, id])
  const valid = !!activeId && effectiveCount >= 1 && effectiveCount <= MAX && tids.length > 0
  return (
    <Dialog open={open} onOpenChange={o => { if (!o && !start.isPending) onClose() }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading">Batch generation</DialogTitle>
          <DialogDescription>Queue several videos for <span className="text-foreground">{active?.identity?.name ?? active?.name ?? "the active persona"}</span>. They are generated one after another in the background; follow the progress on the Projects page.</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-[140px_1fr]">
            <div>
              <Label htmlFor="b-count" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">How many videos</Label>
              <Input id="b-count" type="number" min={1} max={MAX} value={topicsMode === "own" ? ownTopics.length : count} disabled={topicsMode === "own"}
                onChange={e => setCount(Math.max(1, Math.min(MAX, Number(e.target.value) || 1)))} className="font-mono text-base" autoFocus />
              <p className="mt-1 text-[11px] text-muted-foreground">1–{MAX}{topicsMode === "own" ? " · one per topic line" : ""}</p>
            </div>
            <div>
              <Label htmlFor="b-name" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Name <span className="normal-case tracking-normal">(optional)</span></Label>
              <Input id="b-name" value={name} onChange={e => setName(e.target.value)} placeholder={`Batch of ${effectiveCount || count}`} />
            </div>
          </div>
          <div>
            <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Templates <span className="normal-case tracking-normal">· split by the PRD mix (story 10 : list 7 : pov 6 : problem/solution 7)</span></Label>
            <div className="flex flex-wrap gap-1.5">
              {(templates ?? []).map(t => (
                <button key={t.id} type="button" onClick={() => toggle(t.id)}
                  className={cn("rounded-md border px-2.5 py-1 text-sm", tids.includes(t.id) ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{t.name}</button>
              ))}
            </div>
          </div>
          <div>
            <Label htmlFor="b-dur" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Target length · <span className="font-mono text-foreground">{duration}s</span></Label>
            <input id="b-dur" type="range" min={15} max={25} step={1} value={duration} onChange={e => setDuration(Number(e.target.value))} className="scrub w-full" />
          </div>
          <div>
            <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Topics</Label>
            <div className="mb-2 flex gap-1.5">
              <button type="button" onClick={() => setTopicsMode("ai")} className={cn("rounded-md border px-2.5 py-1 text-sm", topicsMode === "ai" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>AI picks them from the persona</button>
              <button type="button" onClick={() => setTopicsMode("own")} className={cn("rounded-md border px-2.5 py-1 text-sm", topicsMode === "own" ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>I'll paste my own</button>
            </div>
            {topicsMode === "ai"
              ? <p className="text-xs text-muted-foreground">{count} topics are generated from the persona's pillars, avoiding topics already used, and spread over the selected templates.</p>
              : <Textarea rows={6} value={own} onChange={e => setOwn(e.target.value)} placeholder={"One topic per line, e.g.\nWhy I stopped answering Slack in the morning\nPOV: you opened your laptop just to check one thing"} />}
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-border pt-4">
          <p className="text-xs text-muted-foreground">Uses OpenAI + ElevenLabs credits for every video.</p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={start.isPending}>Cancel</Button>
            <Button type="button" disabled={!valid || start.isPending} onClick={() => start.mutate()}><Play className="size-4" /> {start.isPending ? "Planning topics…" : `Start ${effectiveCount || count} videos`}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Recent batches for the active persona with live progress; selecting one filters the project list. */
export function BatchList({ selected, onSelect }: { selected: string | null; onSelect: (id: string | null) => void }) {
  const qc = useQueryClient()
  const { activeId } = usePersona()
  const { data } = useQuery({
    queryKey: ["batches", activeId], queryFn: () => api.batches(activeId || undefined), enabled: !!activeId,
    refetchInterval: q => (q.state.data?.some(b => ACTIVE.has(b.status)) ? 3000 : 20000),
  })
  const cancel = useMutation({ mutationFn: api.cancelBatch, onSuccess: () => { toast.success("Batch will stop after the current video"); qc.invalidateQueries({ queryKey: ["batches"] }) }, onError: e => toast.error(e.message) })
  const resume = useMutation({ mutationFn: api.resumeBatch, onSuccess: () => { toast.success("Batch resumed"); qc.invalidateQueries({ queryKey: ["batches"] }) }, onError: e => toast.error(e.message) })
  const batches = (data ?? []).slice(0, 6)
  if (batches.length === 0) return null
  return (
    <div className="px-8 pt-4">
      <div className="mb-2 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground"><Layers className="size-3" /> Batches</div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {batches.map(b => {
          const pct = b.total ? Math.round(((b.done + b.failed) / b.total) * 100) : 0
          const live = ACTIVE.has(b.status)
          const isSel = selected === b.id
          return (
            <div key={b.id} className={cn("rounded-md border bg-card p-3 text-sm", isSel ? "border-primary" : "border-border")}>
              <div className="flex items-start justify-between gap-2">
                <button type="button" className="min-w-0 text-left" onClick={() => onSelect(isSel ? null : b.id)}>
                  <div className="truncate font-heading font-semibold">{b.name}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{b.id} · {fmtDate(b.created_at)} · {b.config.topics_source === "user" ? "own topics" : "AI topics"}</div>
                </button>
                <span className={cn("shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider",
                  b.status === "DONE" ? "bg-ready/15 text-ready" : b.status === "RUNNING" ? "bg-primary/15 text-primary" : b.status === "FAILED" ? "bg-fail/15 text-fail" : "bg-secondary text-muted-foreground")}>
                  {b.cancel_requested && live ? "stopping" : b.status.toLowerCase()}
                </span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded bg-surface-2">
                <div className="flex h-full">
                  <div className="bg-ready" style={{ width: `${b.total ? (b.done / b.total) * 100 : 0}%` }} />
                  <div className="bg-fail" style={{ width: `${b.total ? (b.failed / b.total) * 100 : 0}%` }} />
                  {live && <div className="animate-pulse bg-primary/60" style={{ width: `${b.total ? (b.running / b.total) * 100 : 0}%` }} />}
                </div>
              </div>
              <div className="mt-1.5 flex items-center justify-between font-mono text-[11px] text-muted-foreground">
                <span>{b.done} ready{b.approved ? ` (${b.approved} approved)` : ""} · {b.failed} failed · {b.pending + b.running} left · {pct}%</span>
                <span className="flex gap-1">
                  {live && <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" disabled={b.cancel_requested} onClick={() => cancel.mutate(b.id)}><Square className="size-3" /> stop</button>}
                  {!live && (b.pending + b.failed) > 0 && <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => resume.mutate(b.id)}><Play className="size-3" /> resume</button>}
                  {isSel && <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => onSelect(null)}><X className="size-3" /> clear filter</button>}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
