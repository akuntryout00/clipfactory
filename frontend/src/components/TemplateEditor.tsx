import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { Template } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { useConfirm } from "@/components/ConfirmDialog"

export const EMPTY_TEMPLATE: Template = {
  id: "", name: "", description: "", duration: { min: 15, target: 18, max: 22 },
  sections: [
    { type: "hook", weight: 0.15, guidance: "Pattern-interrupt first line, 1-2 seconds." },
    { type: "body", weight: 0.65, guidance: "The substance." },
    { type: "ending", weight: 0.20, guidance: "Short close." },
  ],
  voiceover: true, caption_style: "dynamic_center", music_category: null, closing: "End on one punchline. No call to action.",
  shot_duration: { min: 1.5, max: 4.0 }, overlays: { min: 1, max: 3 },
}

const MUSIC = ["", "upbeat", "productivity_soft", "minimal", "chill"]

export function TemplateEditor({ template, onClose }: { template: Template | null | "new"; onClose: () => void }) {
  const qc = useQueryClient()
  const confirm = useConfirm()
  const isNew = template === "new"
  const [t, setT] = useState<Template>(EMPTY_TEMPLATE)
  useEffect(() => { setT(template && template !== "new" ? structuredClone(template) : EMPTY_TEMPLATE) }, [template])
  const { data: styles } = useQuery({ queryKey: ["caption-styles"], queryFn: api.captionStyles })

  const total = t.sections.reduce((a, s) => a + (Number(s.weight) || 0), 0)
  const totalOk = Math.abs(total - 1) < 0.001
  const durOk = t.duration.min <= t.duration.target && t.duration.target <= t.duration.max
  const idOk = /^[a-z0-9][a-z0-9_-]{1,40}$/.test(t.id)
  const sectionsOk = t.sections.length > 0 && t.sections.every(s => /^[a-z0-9_]+$/.test(s.type) && s.weight > 0)
  const valid = totalOk && durOk && idOk && sectionsOk && t.name.trim().length > 0

  const invalidate = () => { qc.invalidateQueries({ queryKey: ["templates"] }) }
  const save = useMutation({
    mutationFn: () => (isNew ? api.createTemplate(t) : api.updateTemplate(t)),
    onSuccess: () => { toast.success(isNew ? `Template ${t.id} created` : `Template ${t.id} saved`); invalidate(); onClose() },
    onError: e => toast.error(e.message),
  })
  const del = useMutation({
    mutationFn: () => api.deleteTemplate(t.id),
    onSuccess: () => { toast.success(`Template ${t.id} deleted`); invalidate(); onClose() },
    onError: e => toast.error(e.message),
  })
  const setSec = (i: number, patch: Partial<Template["sections"][number]>) =>
    setT(x => ({ ...x, sections: x.sections.map((s, j) => (j === i ? { ...s, ...patch } : s)) }))
  const move = (i: number, d: -1 | 1) => setT(x => {
    const arr = [...x.sections]; const j = i + d
    if (j < 0 || j >= arr.length) return x
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
    return { ...x, sections: arr }
  })
  const normalize = () => setT(x => {
    const sum = x.sections.reduce((a, s) => a + (Number(s.weight) || 0), 0) || 1
    const secs = x.sections.map(s => ({ ...s, weight: Math.round(((Number(s.weight) || 0) / sum) * 100) / 100 }))
    const diff = Math.round((1 - secs.reduce((a, s) => a + s.weight, 0)) * 100) / 100
    if (secs.length) secs[secs.length - 1].weight = Math.round((secs[secs.length - 1].weight + diff) * 100) / 100
    return { ...x, sections: secs }
  })

  return (
    <Dialog open={template !== null} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="font-heading">{isNew ? "New template" : `Edit template · ${t.id}`}</DialogTitle>
          <DialogDescription>Templates are saved as JSON in <code className="font-mono">configs/templates/</code>. The LLM writes one text per section, in order, sized by weight.</DialogDescription>
        </DialogHeader>
        <form className="grid gap-4 text-sm" onSubmit={e => { e.preventDefault(); if (valid) save.mutate() }}>
          <div className="grid grid-cols-3 gap-3">
            <div><Label className="text-xs text-muted-foreground">id (folder-safe, cannot change later)</Label>
              <Input value={t.id} disabled={!isNew} onChange={e => setT(x => ({ ...x, id: e.target.value.toLowerCase() }))} placeholder="story_fast_v1" className={cn(!idOk && t.id && "border-fail")} /></div>
            <div><Label className="text-xs text-muted-foreground">Name</Label><Input value={t.name} onChange={e => setT(x => ({ ...x, name: e.target.value }))} placeholder="Story (fast)" /></div>
            <div><Label className="text-xs text-muted-foreground">Music category</Label>
              <select value={t.music_category ?? ""} onChange={e => setT(x => ({ ...x, music_category: e.target.value || null }))} className="h-9 w-full rounded-md border border-input bg-card px-2">
                {MUSIC.map(m => <option key={m} value={m}>{m || "— none —"}</option>)}
              </select></div>
          </div>
          <div><Label className="text-xs text-muted-foreground">Description (shown to the LLM and in the Generate screen)</Label>
            <Textarea rows={2} value={t.description} onChange={e => setT(x => ({ ...x, description: e.target.value }))} /></div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">Sections (in order) · weights must sum to 100%</Label>
              <div className="flex items-center gap-2">
                <span className={cn("font-mono text-[11px]", totalOk ? "text-ready" : "text-fail")}>total {Math.round(total * 100)}%</span>
                {!totalOk && <Button type="button" size="sm" variant="outline" onClick={normalize}>Normalize</Button>}
                <Button type="button" size="sm" variant="outline" onClick={() => setT(x => ({ ...x, sections: [...x.sections, { type: "", weight: 0.1, guidance: "" }] }))}><Plus className="size-3.5" /> Section</Button>
              </div>
            </div>
            <div className="flex h-2 overflow-hidden rounded bg-surface-2">
              {t.sections.map((s, i) => <div key={i} style={{ width: `${Math.max(0, s.weight) * 100}%` }} className={i % 2 ? "bg-primary/40" : "bg-primary/70"} title={s.type} />)}
            </div>
            <ul className="mt-2 space-y-1.5">
              {t.sections.map((s, i) => (
                <li key={i} className="grid grid-cols-[140px_80px_1fr_auto] items-center gap-2">
                  <Input value={s.type} onChange={e => setSec(i, { type: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} placeholder="hook" className="font-mono text-xs" />
                  <div className="relative"><Input type="number" min={1} max={100} step={1} value={Math.round(s.weight * 100)} onChange={e => setSec(i, { weight: Number(e.target.value) / 100 })} className="pr-6 font-mono text-xs" /><span className="absolute right-2 top-2 text-xs text-muted-foreground">%</span></div>
                  <Input value={s.guidance} onChange={e => setSec(i, { guidance: e.target.value })} placeholder="What this section should do" className="text-xs" />
                  <div className="flex gap-0.5">
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => move(i, -1)} aria-label="Move up"><ArrowUp className="size-3.5" /></Button>
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => move(i, 1)} aria-label="Move down"><ArrowDown className="size-3.5" /></Button>
                    <Button type="button" variant="ghost" size="icon-sm" onClick={() => setT(x => ({ ...x, sections: x.sections.filter((_, j) => j !== i) }))} aria-label="Remove"><Trash2 className="size-3.5 text-muted-foreground" /></Button>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <fieldset className="rounded-md border border-border p-2">
              <legend className="px-1 text-[11px] text-muted-foreground">Duration (s)</legend>
              <div className="grid grid-cols-3 gap-1">
                {(["min", "target", "max"] as const).map(k => <div key={k}><Label className="text-[10px] text-muted-foreground">{k}</Label><Input type="number" step={1} value={t.duration[k]} onChange={e => setT(x => ({ ...x, duration: { ...x.duration, [k]: Number(e.target.value) } }))} className={cn("font-mono text-xs", !durOk && "border-fail")} /></div>)}
              </div>
            </fieldset>
            <fieldset className="rounded-md border border-border p-2">
              <legend className="px-1 text-[11px] text-muted-foreground">Shot length (s)</legend>
              <div className="grid grid-cols-2 gap-1">
                {(["min", "max"] as const).map(k => <div key={k}><Label className="text-[10px] text-muted-foreground">{k}</Label><Input type="number" step={0.5} value={t.shot_duration[k]} onChange={e => setT(x => ({ ...x, shot_duration: { ...x.shot_duration, [k]: Number(e.target.value) } }))} className="font-mono text-xs" /></div>)}
              </div>
            </fieldset>
            <fieldset className="rounded-md border border-border p-2">
              <legend className="px-1 text-[11px] text-muted-foreground">Creative overlays per video</legend>
              <div className="grid grid-cols-2 gap-1">
                {(["min", "max"] as const).map(k => <div key={k}><Label className="text-[10px] text-muted-foreground">{k}</Label><Input type="number" step={1} value={t.overlays[k]} onChange={e => setT(x => ({ ...x, overlays: { ...x.overlays, [k]: Number(e.target.value) } }))} className="font-mono text-xs" /></div>)}
              </div>
            </fieldset>
          </div>

          <div className="grid grid-cols-[1fr_auto_auto] items-end gap-3">
            <div><Label className="text-xs text-muted-foreground">Closing rule (how scripts of this template end)</Label>
              <Input value={t.closing ?? ""} onChange={e => setT(x => ({ ...x, closing: e.target.value || null }))} placeholder="End on one reflective punchline. No call to action." /></div>
            <div><Label className="text-xs text-muted-foreground">Caption style</Label>
              <select value={t.caption_style} onChange={e => setT(x => ({ ...x, caption_style: e.target.value }))} className="h-9 rounded-md border border-input bg-card px-2">
                {(styles ?? [t.caption_style]).map(s => <option key={s}>{s}</option>)}
              </select></div>
            <label className="flex h-9 items-center gap-2"><input type="checkbox" checked={t.voiceover} onChange={e => setT(x => ({ ...x, voiceover: e.target.checked }))} className="scrub size-4" /> Voice-over</label>
          </div>

          <div className="flex items-center gap-2 pt-1">
            {!isNew && <Button type="button" variant="ghost" className="text-fail hover:text-fail" onClick={async () => { if (await confirm({ title: "Delete this template?", subject: `${t.name} · ${t.id}`, description: "Existing projects keep the id, but new videos can no longer use it.", confirmLabel: "Delete template" })) del.mutate() }}><Trash2 className="size-4" /> Delete</Button>}
            <span className="flex-1" />
            {!valid && <span className="text-[11px] text-muted-foreground">{!idOk ? "id: lowercase letters, digits, _ or -" : !totalOk ? "weights must sum to 100%" : !durOk ? "min ≤ target ≤ max" : !sectionsOk ? "every section needs a type and weight" : "name required"}</span>}
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!valid || save.isPending}>{isNew ? "Create template" : "Save template"}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
