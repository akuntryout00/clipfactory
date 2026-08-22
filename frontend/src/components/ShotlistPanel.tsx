import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ChevronDown, ChevronUp, ClipboardList, Sparkles, Wand2, X } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { Shotlist, ShotlistItem } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

/**
 * Target B-roll list for the active persona: what to film, how much of it is already in the library (%), regenerate with AI.
 * Selecting an item filters the clip grid to the clips assigned to it.
 */
export function ShotlistPanel({ personaId, selectedItem, onSelectItem }: { personaId: string; selectedItem: string | null; onSelectItem: (id: string | null) => void }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ["shotlist", personaId], queryFn: () => api.shotlist(personaId), enabled: !!personaId })
  const [open, setOpen] = useState(false)
  const [genOpen, setGenOpen] = useState(false)
  const [cat, setCat] = useState<string | null>(null)
  const [onlyMissing, setOnlyMissing] = useState(false)
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["shotlist", personaId] }); qc.invalidateQueries({ queryKey: ["assets"] }) }
  const match = useMutation({
    mutationFn: () => api.matchShotlist(personaId, { only_unassigned: true }),
    onSuccess: d => { toast.success(`${d.matched ?? 0} clips matched to the shot list`); invalidate() },
    onError: e => toast.error(e.message),
  })
  const cats = useMemo(() => Array.from(new Set((data?.items ?? []).map(i => i.category))), [data])
  const items = useMemo(() => (data?.items ?? []).filter(i => (!cat || i.category === cat) && (!onlyMissing || !i.done)), [data, cat, onlyMissing])
  if (!personaId) return null
  const has = !!data && data.items_total > 0
  return (
    <div className="mx-8 mt-4 rounded-md border border-border bg-card">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <ClipboardList className="size-4 text-primary" />
        <div className="min-w-0 flex-1">
          {isLoading ? <span className="text-sm text-muted-foreground">Loading shot list…</span> : has ? (
            <>
              <div className="flex items-baseline gap-2">
                <span className="font-heading text-lg font-semibold">{data.percent}%</span>
                <span className="text-sm text-muted-foreground">of the target B-roll is in the library · {data.filled}/{data.wanted} clips · {data.items_done}/{data.items_total} shots complete{data.unassigned_count ? ` · ${data.unassigned_count} clips not matched to any shot` : ""}</span>
              </div>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-surface-2"><div className="h-full bg-primary" style={{ width: `${Math.min(100, data.percent)}%` }} /></div>
            </>
          ) : (
            <span className="text-sm text-muted-foreground">No target shot list yet — let AI plan what to film for this persona, then track how much of it you've uploaded.</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {has && data.unassigned_count > 0 && <Button size="sm" variant="outline" onClick={() => match.mutate()} disabled={match.isPending}><Wand2 className="size-3.5" /> {match.isPending ? "Matching…" : "Match clips with AI"}</Button>}
          <Button size="sm" variant={has ? "outline" : "default"} onClick={() => setGenOpen(true)}><Sparkles className="size-3.5" /> {has ? "Regenerate list" : "Generate shot list"}</Button>
          {has && <Button size="sm" variant="ghost" onClick={() => setOpen(o => !o)}>{open ? <><ChevronUp className="size-4" /> Hide list</> : <><ChevronDown className="size-4" /> Show list</>}</Button>}
        </div>
      </div>
      {has && open && (
        <div className="border-t border-border px-4 py-3">
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            <button type="button" onClick={() => setCat(null)} className={cn("rounded-md border px-2 py-0.5 font-mono text-[11px]", !cat ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>all</button>
            {cats.map(c => {
              const its = data.items.filter(i => i.category === c)
              const f = its.reduce((a, i) => a + i.filled, 0), w = its.reduce((a, i) => a + i.count, 0)
              return <button key={c} type="button" onClick={() => setCat(cat === c ? null : c)} className={cn("rounded-md border px-2 py-0.5 font-mono text-[11px]", cat === c ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{c} <span className="opacity-70">{f}/{w}</span></button>
            })}
            <span className="flex-1" />
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground"><input type="checkbox" className="scrub size-3.5" checked={onlyMissing} onChange={e => setOnlyMissing(e.target.checked)} /> only missing</label>
            {selectedItem && <button type="button" className="inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-foreground" onClick={() => onSelectItem(null)}><X className="size-3" /> clear clip filter</button>}
            <span className="font-mono text-[11px] text-muted-foreground">{data.generated_at ? `generated ${new Date(data.generated_at).toLocaleDateString()}` : ""}{data.target_count ? ` · target ${data.target_count}` : ""}</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {items.map(it => <ShotCard key={it.id} item={it} selected={selectedItem === it.id} onSelect={() => onSelectItem(selectedItem === it.id ? null : it.id)} />)}
            {items.length === 0 && <p className="text-sm text-muted-foreground">Nothing to show for this filter.</p>}
          </div>
        </div>
      )}
      <GenerateDialog open={genOpen} onClose={() => setGenOpen(false)} personaId={personaId} current={data ?? null} onDone={invalidate} />
    </div>
  )
}

function ShotCard({ item, selected, onSelect }: { item: ShotlistItem; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className={cn("rounded-md border p-2.5 text-left text-sm transition-colors hover:border-primary/60", selected ? "border-primary bg-primary/5" : item.done ? "border-ready/40 bg-ready/5" : "border-border bg-background")}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{item.title}</div>
          <div className="font-mono text-[10px] text-muted-foreground">{item.category} · {item.shot ?? "—"} · {item.action ?? "—"}</div>
        </div>
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px]", item.done ? "bg-ready/15 text-ready" : item.filled > 0 ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground")}>
          {item.done ? <Check className="inline size-3" /> : null} {item.filled}/{item.count}
        </span>
      </div>
      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={item.description}>{item.description}</p>
    </button>
  )
}

function GenerateDialog({ open, onClose, personaId, current, onDone }: { open: boolean; onClose: () => void; personaId: string; current: Shotlist | null; onDone: () => void }) {
  const [target, setTarget] = useState(100)
  const [guidance, setGuidance] = useState("")
  useEffect(() => { if (open) { setTarget(current?.target_count ?? 100); setGuidance(current?.guidance ?? "") } }, [open, current])
  const gen = useMutation({
    mutationFn: () => api.generateShotlist(personaId, { target_count: target, guidance: guidance.trim() || null, match_existing: true }),
    onSuccess: d => { toast.success(`Shot list ready — ${d.items_total} shots for ${d.wanted} clips, ${d.percent}% already covered`); onDone(); onClose() },
    onError: e => toast.error(e.message),
  })
  const has = !!current && current.items_total > 0
  return (
    <Dialog open={open} onOpenChange={o => { if (!o && !gen.isPending) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading">{has ? "Regenerate the shot list" : "Plan the B-roll to film"}</DialogTitle>
          <DialogDescription>AI writes a concrete list of shots for this persona (framing, action, place) grouped by folder. {has ? "The current list is replaced; clips already matched keep their place when the same shot still exists." : "You then film and upload them; the B-roll page tracks the coverage."}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="sl-target" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Target number of clips</Label>
            <Input id="sl-target" type="number" min={5} max={400} value={target} onChange={e => setTarget(Math.max(5, Math.min(400, Number(e.target.value) || 5)))} className="w-40 font-mono text-base" />
            <p className="mt-1 text-[11px] text-muted-foreground">The PRD targets 100 clips per persona. Shots get a count each; counts add up to this number.</p>
          </div>
          <div>
            <Label htmlFor="sl-guid" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Guidance <span className="normal-case tracking-normal">(optional)</span></Label>
            <Textarea id="sl-guid" rows={3} value={guidance} onChange={e => setGuidance(e.target.value)} placeholder="e.g. mostly cafe + home office, no gym, include my bike commute, winter clothes" />
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={gen.isPending}>Cancel</Button>
          <Button type="button" onClick={() => gen.mutate()} disabled={gen.isPending}><Sparkles className="size-4" /> {gen.isPending ? "Planning with AI…" : has ? "Regenerate" : "Generate"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Small select used in the upload / edit dialogs: which target shot does this clip fulfil. */
export function ShotlistItemSelect({ personaId, value, onChange, className }: { personaId: string; value: string | null | undefined; onChange: (v: string | null) => void; className?: string }) {
  const { data } = useQuery({ queryKey: ["shotlist", personaId], queryFn: () => api.shotlist(personaId), enabled: !!personaId })
  const items = data?.items ?? []
  if (items.length === 0) return null
  const cats = Array.from(new Set(items.map(i => i.category)))
  return (
    <select value={value ?? ""} onChange={e => onChange(e.target.value || null)} className={cn("h-9 w-full rounded-md border border-input bg-card px-2 text-sm", className)}>
      <option value="">— not assigned to a target shot —</option>
      {cats.map(c => <optgroup key={c} label={c}>{items.filter(i => i.category === c).map(i => <option key={i.id} value={i.id}>{i.title} ({i.filled}/{i.count})</option>)}</optgroup>)}
    </select>
  )
}
