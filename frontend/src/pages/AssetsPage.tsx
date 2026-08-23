import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FolderInput, Sparkles, Trash2, Upload, Wand2 } from "lucide-react"
import { toast } from "sonner"
import { api, media } from "@/lib/api"
import { personaLabel, usePersona } from "@/lib/persona"
import { ShotlistItemSelect, ShotlistPanel } from "@/components/ShotlistPanel"
import type { Asset, Persona } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { RangeTrimmer } from "@/components/RangeTrimmer"
import { useConfirm } from "@/components/ConfirmDialog"

export default function AssetsPage() {
  const qc = useQueryClient()
  const { activeId, active, personas } = usePersona()
  const [kind, setKind] = useState<"video" | "image">("video")
  const { data, isLoading } = useQuery({ queryKey: ["assets", activeId, kind], queryFn: () => api.assets(activeId || undefined, kind), enabled: !!activeId })
  const [q, setQ] = useState("")
  const [cat, setCat] = useState("ALL")
  const [edit, setEdit] = useState<Asset | null>(null)
  const [adding, setAdding] = useState(false)
  const [shotItem, setShotItem] = useState<string | null>(null)
  useEffect(() => { setShotItem(null) }, [activeId])
  const imp = useMutation({ mutationFn: api.importAssets, onSuccess: r => { toast.success(`Imported: ${r.created} new, ${r.updated} refreshed`); qc.invalidateQueries({ queryKey: ["assets"] }) }, onError: e => toast.error(e.message) })
  const enrich = useMutation({ mutationFn: api.enrichAssets, onSuccess: r => { toast.success(`Enriched ${r.enriched} clips`); qc.invalidateQueries({ queryKey: ["assets"] }) }, onError: e => toast.error(e.message) })
  // files live under assets/<persona>/<category>/; the category is the second path segment
  const catOf = (a: Asset) => { const parts = a.file.split("/"); return parts.length >= 3 ? parts[1] : parts[0] }
  const cats = useMemo(() => Array.from(new Set((data ?? []).map(catOf))).sort(), [data])
  const rows = useMemo(() => (data ?? []).filter(a => (cat === "ALL" || catOf(a) === cat) && (!shotItem || a.shotlist_item_id === shotItem) &&
    (!q || [a.id, a.file, a.description, a.action, a.location, a.mood, ...(a.tags ?? [])].join(" ").toLowerCase().includes(q.toLowerCase()))), [data, q, cat, shotItem])
  const approved = (data ?? []).filter(a => a.approved).length

  return (
    <div>
      <PageHeader eyebrow="Asset library" title={kind === "image" ? "Photos" : "B-roll"}
        actions={<>
          <Button size="sm" onClick={() => setAdding(true)}><Upload className="size-4" /> {kind === "image" ? "Add photo" : "Add video"}</Button>
          <Button variant="outline" size="sm" onClick={() => imp.mutate()} disabled={imp.isPending}><FolderInput className="size-4" /> {imp.isPending ? "Importing…" : "Import folder"}</Button>
          <Button variant="outline" size="sm" onClick={() => enrich.mutate()} disabled={enrich.isPending}><Sparkles className="size-4" /> {enrich.isPending ? "Enriching…" : "Enrich with AI"}</Button>
        </>}>
        <p className="mt-1 text-sm text-muted-foreground"><span className="text-foreground">{personaLabel(active)}</span> · {data?.length ?? 0} clips · {approved} approved · drop new files into <code className="font-mono">assets/{activeId || "<persona>"}/&lt;category&gt;/</code> then Import.</p>
      </PageHeader>
      <div className="flex items-center gap-1 px-8 pt-4">
        {(["video", "image"] as const).map(k => (
          <button key={k} type="button" onClick={() => { setKind(k); setCat("ALL"); setShotItem(null) }} className={cn("rounded-md border px-3 py-1.5 text-sm", kind === k ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{k === "video" ? "Videos (B-roll)" : "Photos (slideshows)"}</button>
        ))}
        <span className="ml-2 text-[11px] text-muted-foreground">{kind === "image" ? "Photos are used by the Slideshow template: one bold line of text per photo." : "Clips are used by the video templates."}</span>
      </div>
      {kind === "video" && <ShotlistPanel personaId={activeId} selectedItem={shotItem} onSelectItem={setShotItem} />}
      <div className="flex flex-wrap items-center gap-2 px-8 py-4">
        <Input placeholder="Search id, tags, description…" value={q} onChange={e => setQ(e.target.value)} className="h-8 w-72" />
        <div className="flex gap-1">
          {["ALL", ...cats].map(c => (
            <button key={c} onClick={() => setCat(c)} className={cn("rounded-md border px-2 py-1 font-mono text-[11px]", cat === c ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{c}</button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 px-8 pb-10 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {rows.map(a => (
          <button key={a.id} type="button" onClick={() => setEdit(a)}
            className={cn("group rounded-md border bg-card p-1.5 text-left transition-colors hover:border-primary focus-visible:outline-2 focus-visible:outline-ring", a.approved ? "border-border" : "border-fail/40")}>
            <div className="relative aspect-[9/16] overflow-hidden rounded bg-surface-2">
              <img src={media.assetThumb(a.id)} alt="" loading="lazy" className="h-full w-full object-cover" />
              <span className="absolute left-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">{a.id.replace("asset_", "#")}</span>
              <span className="absolute right-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">{a.kind === "image" ? `${a.width ?? "?"}×${a.height ?? "?"}` : `${a.duration.toFixed(1)}s`}</span>
              {!a.approved && <span className="absolute bottom-1 left-1 rounded bg-fail/80 px-1 font-mono text-[10px] text-background">not approved</span>}
              {a.usage_count > 0 && <span className="absolute bottom-1 right-1 rounded bg-background/80 px-1 font-mono text-[10px]">×{a.usage_count}</span>}
            </div>
            <div className="mt-1 truncate font-mono text-[11px]">{a.file.split("/").pop()}</div>
            <div className="truncate text-[11px] text-muted-foreground">{a.action} · {a.shot} · q{a.quality_score.toFixed(2)}</div>
          </button>
        ))}
      </div>
      <AssetDialog asset={edit} onClose={() => setEdit(null)} />
      <UploadDialog open={adding} onClose={() => setAdding(false)} categories={cats} personas={personas} defaultPersona={activeId} />
    </div>
  )
}

function UploadDialog({ open, onClose, categories, personas, defaultPersona }: { open: boolean; onClose: () => void; categories: string[]; personas: Persona[]; defaultPersona: string }) {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [personaId, setPersonaId] = useState(defaultPersona)
  const [shotItem, setShotItem] = useState<string | null>(null)
  useEffect(() => { setPersonaId(defaultPersona); setShotItem(null) }, [defaultPersona, open])
  const [category, setCategory] = useState(categories[0] ?? "desk")
  const [newCat, setNewCat] = useState("")
  const [description, setDescription] = useState("")
  const [tags, setTags] = useState("")
  const [approved, setApproved] = useState(true)
  const [pct, setPct] = useState(0)
  const [range, setRange] = useState<{ s: number; e: number; dur: number } | null>(null)
  const [ai, setAi] = useState(true)
  const [meta, setMeta] = useState({ action: "", location: "", shot: "", mood: "", quality: 0.8 })
  const [notes, setNotes] = useState<string | null>(null)
  const cat = category === "__new__" ? newCat.trim().toLowerCase() : category
  const reset = () => { setFile(null); setDescription(""); setTags(""); setPct(0); setNewCat(""); setRange(null); setMeta({ action: "", location: "", shot: "", mood: "", quality: 0.8 }); setNotes(null) }
  const analyze = useMutation({
    mutationFn: (f: File) => api.analyzeAsset(f),
    onSuccess: a => {
      setDescription(a.description); setTags(a.tags.join(", ")); setNotes(a.notes)
      setMeta({ action: a.action, location: a.location, shot: a.shot, mood: a.mood, quality: a.quality_score })
      if (a.suggested_category && categories.includes(a.suggested_category)) setCategory(a.suggested_category)
      else if (a.suggested_category) { setCategory("__new__"); setNewCat(a.suggested_category) }
      toast.success(`AI filled the fields from ${a.frames_analyzed} frames — review and upload`)
    },
    onError: e => toast.error(`AI autocomplete failed: ${e.message}`),
  })
  const pickFile = (f: File | null) => { setFile(f); if (f && ai) analyze.mutate(f) }
  const up = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append("file", file!); fd.append("category", cat); fd.append("persona_id", personaId); if (shotItem) fd.append("shotlist_item_id", shotItem); fd.append("description", description); fd.append("tags", tags); fd.append("approved", String(approved))
      if (range) { fd.append("usable_start", String(range.s)); fd.append("usable_end", String(range.e)) }
      if (meta.action) fd.append("action", meta.action); if (meta.location) fd.append("location", meta.location)
      if (meta.shot) fd.append("shot", meta.shot); if (meta.mood) fd.append("mood", meta.mood); fd.append("quality_score", String(meta.quality))
      return api.uploadAsset(fd, setPct)
    },
    onSuccess: a => {
      if (a.enriched) toast.success(`Added ${a.id} · AI tags added (${a.tags.length} tags)`)
      else toast.warning(`Added ${a.id} — AI enrichment skipped${a.enrichError ? `: ${a.enrichError}` : ""}`)
      qc.invalidateQueries({ queryKey: ["assets"] }); qc.invalidateQueries({ queryKey: ["shotlist"] }); reset(); onClose()
    },
    onError: e => toast.error(e.message),
  })
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) { reset(); onClose() } }}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader><DialogTitle className="font-heading">Add a B-roll clip</DialogTitle></DialogHeader>
        <form noValidate className="grid gap-4 md:grid-cols-[300px_1fr]" onSubmit={e => { e.preventDefault(); if (file && cat) up.mutate() }}>
          <div>
            {previewUrl && file?.type.startsWith("image/") ? (
              <img src={previewUrl} alt="" className="max-h-72 w-full rounded-md border border-border object-contain" />
            ) : previewUrl ? (
              <RangeTrimmer src={previewUrl} duration={range?.dur ?? 0} start={range?.s ?? 0} end={range?.e ?? 0}
                onChange={(s, e) => setRange(r => ({ s, e, dur: r?.dur ?? e }))} />
            ) : (
              <label className="block aspect-[9/16] cursor-pointer overflow-hidden rounded-md border border-dashed border-border bg-surface-2 hover:border-primary">
                <span className="grid h-full place-items-center p-4 text-center text-xs text-muted-foreground">Click to choose a video<br />(.mp4 / .mov, vertical 9:16 preferred)</span>
                <input type="file" accept="video/mp4,video/quicktime,.mp4,.mov,.m4v,image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" className="sr-only" onChange={e => pickFile(e.target.files?.[0] ?? null)} />
              </label>
            )}
            {/* hidden probe to learn the duration and seed the range to whole clip minus small margins */}
            {previewUrl && !range && !file?.type.startsWith("image/") && <video src={previewUrl} className="hidden" preload="metadata"
              onLoadedMetadata={e => { const d = e.currentTarget.duration; const m = Math.min(0.2, d * 0.05); setRange({ s: Math.round(m * 20) / 20, e: Math.round((d - m) * 20) / 20, dur: d }) }} />}
            {file && <div className="mt-1 flex items-center justify-between gap-2 font-mono text-[11px] text-muted-foreground">
              <span className="truncate">{file.name} · {(file.size / 1e6).toFixed(1)} MB</span>
              <button type="button" className="text-primary underline" onClick={() => { setFile(null); setRange(null) }}>change file</button>
            </div>}
          </div>
          <div className="grid content-start gap-3 text-sm">
            <label className={cn("flex items-center gap-2 rounded-md border px-3 py-2", ai ? "border-primary/50 bg-primary/5" : "border-border")}>
              <input type="checkbox" checked={ai} onChange={e => setAi(e.target.checked)} className="scrub size-4" />
              <Wand2 className="size-4 text-primary" />
              <span className="flex-1"><b>AI autocomplete</b> — analyze the video frames and fill every field; you can still edit before uploading</span>
              {analyze.isPending && <span className="animate-pulse font-mono text-[11px] text-primary">analyzing…</span>}
              {file && !analyze.isPending && ai && <button type="button" className="font-mono text-[11px] text-primary underline" onClick={() => analyze.mutate(file)}>re-run</button>}
            </label>
            <div>
              <Label className="text-xs text-muted-foreground">Persona (owner of this clip)</Label>
              <select value={personaId} onChange={e => setPersonaId(e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-2">
                {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <p className="mt-1 text-[11px] text-muted-foreground">Saved to <code className="font-mono">assets/{personaId || "<persona>"}/{cat || "<category>"}/</code></p>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Target shot this clip fulfils</Label>
              <ShotlistItemSelect personaId={personaId} value={shotItem} onChange={setShotItem} />
              <p className="mt-1 text-[11px] text-muted-foreground">Leave empty and AI matches it to the shot list after upload.</p>
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Category (folder)</Label>
              <div className="flex gap-2">
                <select value={category} onChange={e => setCategory(e.target.value)} className="h-9 flex-1 rounded-md border border-input bg-card px-2">
                  {categories.map(c => <option key={c} value={c}>{c}</option>)}
                  <option value="__new__">+ new category…</option>
                </select>
                {category === "__new__" && <Input placeholder="e.g. meeting" value={newCat} onChange={e => setNewCat(e.target.value)} className="flex-1" />}
              </div>
            </div>
            <div><Label className="text-xs text-muted-foreground">Description (what is visible — drives B-roll matching)</Label>
              <Textarea rows={2} value={description} onChange={e => setDescription(e.target.value)} placeholder="POV hand writing in a notebook at a cafe table, coffee beside" /></div>
            <div><Label className="text-xs text-muted-foreground">Tags (comma separated)</Label><Input value={tags} onChange={e => setTags(e.target.value)} placeholder="notebook, writing, hand, cafe" /></div>
            <div className="grid grid-cols-2 gap-2">
              <div><Label className="text-xs text-muted-foreground">Action</Label><Input value={meta.action} onChange={e => setMeta(m => ({ ...m, action: e.target.value }))} placeholder="writing_notebook" /></div>
              <div><Label className="text-xs text-muted-foreground">Location</Label><Input value={meta.location} onChange={e => setMeta(m => ({ ...m, location: e.target.value }))} placeholder="cafe" /></div>
              <div><Label className="text-xs text-muted-foreground">Shot</Label>
                <select value={meta.shot} onChange={e => setMeta(m => ({ ...m, shot: e.target.value }))} className="h-9 w-full rounded-md border border-input bg-card px-2">
                  <option value="">—</option>{["close", "medium", "wide"].map(s => <option key={s}>{s}</option>)}</select></div>
              <div><Label className="text-xs text-muted-foreground">Mood</Label>
                <select value={meta.mood} onChange={e => setMeta(m => ({ ...m, mood: e.target.value }))} className="h-9 w-full rounded-md border border-input bg-card px-2">
                  <option value="">—</option>{["neutral", "focused", "stressed", "relaxed", "happy", "energetic"].map(s => <option key={s}>{s}</option>)}</select></div>
              <div><Label className="text-xs text-muted-foreground">Quality (0–1)</Label><Input type="number" step="0.05" min={0} max={1} value={meta.quality} onChange={e => setMeta(m => ({ ...m, quality: Number(e.target.value) }))} /></div>
              <label className="flex items-end gap-2 pb-2"><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} className="scrub size-4" /> Approved for use right away</label>
            </div>
            {notes && <p className="rounded-md border border-primary/30 bg-primary/5 px-2 py-1 text-[11px] text-muted-foreground"><span className="font-mono text-primary">AI note</span> {notes}</p>}
            {up.isPending && <div className="h-1.5 overflow-hidden rounded bg-surface-2"><div className="h-full bg-primary transition-[width]" style={{ width: `${pct}%` }} /></div>}
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="ghost" onClick={() => { reset(); onClose() }}>Cancel</Button>
              <Button type="submit" disabled={!file || !cat || up.isPending || analyze.isPending}>{up.isPending ? (pct < 100 ? `Uploading ${pct}%` : "Analyzing with AI…") : "Upload clip"}</Button>
            </div>
            <p className="text-[11px] text-muted-foreground">After upload the clip is enriched with AI automatically (tags, action, location, mood from your description) — a good description = better B-roll matching.</p>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function AssetDialog({ asset, onClose }: { asset: Asset | null; onClose: () => void }) {
  const qc = useQueryClient()
  const confirm = useConfirm()
  const [form, setForm] = useState<Partial<Asset>>({})
  const a = asset ? { ...asset, ...form } : null
  const save = useMutation({
    mutationFn: () => api.patchAsset(asset!.id, form),
    onSuccess: () => { toast.success("Saved"); qc.invalidateQueries({ queryKey: ["assets"] }); qc.invalidateQueries({ queryKey: ["shotlist"] }); setForm({}); onClose() },
    onError: e => toast.error(e.message),
  })
  const del = useMutation({
    mutationFn: () => api.deleteAsset(asset!.id),
    onSuccess: () => { toast.success(`Deleted ${asset!.id}`); qc.invalidateQueries({ queryKey: ["assets"] }); setForm({}); onClose() },
    onError: e => toast.error(e.message),
  })
  const set = (k: keyof Asset, v: unknown) => setForm(f => ({ ...f, [k]: v }))
  return (
    <Dialog open={!!asset} onOpenChange={o => { if (!o) { setForm({}); onClose() } }}>
      <DialogContent className="sm:max-w-5xl">
        {a && (<>
          <DialogHeader><DialogTitle className="font-heading">{a.id} <span className="font-mono text-sm font-normal text-muted-foreground">{a.file}</span></DialogTitle></DialogHeader>
          <div className="grid gap-5 md:grid-cols-[300px_1fr]">
            <div className="space-y-2">
              {a.kind === "image" ? (
                <img src={media.assetFile(a.id)} alt="" className="w-full rounded-md border border-border object-contain" />
              ) : (
                <RangeTrimmer src={media.assetFile(a.id)} duration={a.duration} start={a.usable_start} end={a.usable_end}
                  onChange={(s, e) => setForm(f => ({ ...f, usable_start: s, usable_end: e }))} />
              )}
              <div className="font-mono text-[11px] text-muted-foreground">{a.width}×{a.height}{a.kind === "image" ? " · photo" : ` · ${a.fps?.toFixed(2)} fps · ${a.duration.toFixed(2)}s`} · used ×{a.usage_count}</div>
            </div>
            <form noValidate className="grid grid-cols-2 content-start gap-3 text-sm" onSubmit={e => { e.preventDefault(); save.mutate() }}>
              <div className="col-span-2"><Label className="text-xs text-muted-foreground">Description</Label><Textarea rows={2} value={a.description ?? ""} onChange={e => set("description", e.target.value)} /></div>
              <div className="col-span-2"><Label className="text-xs text-muted-foreground">Tags (comma separated)</Label><Input value={(a.tags ?? []).join(", ")} onChange={e => set("tags", e.target.value.split(",").map(s => s.trim()).filter(Boolean))} /></div>
              <div><Label className="text-xs text-muted-foreground">Action</Label><Input value={a.action ?? ""} onChange={e => set("action", e.target.value)} /></div>
              <div><Label className="text-xs text-muted-foreground">Location</Label><Input value={a.location ?? ""} onChange={e => set("location", e.target.value)} /></div>
              <div><Label className="text-xs text-muted-foreground">Shot</Label>
                <select value={a.shot ?? ""} onChange={e => set("shot", e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-2">
                  <option value="">—</option>{["close", "medium", "wide"].map(s => <option key={s}>{s}</option>)}
                </select></div>
              <div><Label className="text-xs text-muted-foreground">Mood</Label>
                <select value={a.mood ?? ""} onChange={e => set("mood", e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-2">
                  <option value="">—</option>{["neutral", "focused", "stressed", "relaxed", "happy"].map(s => <option key={s}>{s}</option>)}
                </select></div>
              <div className="col-span-2"><Label className="text-xs text-muted-foreground">Target shot this clip fulfils</Label>
                <ShotlistItemSelect personaId={a.persona_id ?? ""} value={a.shotlist_item_id} onChange={v => set("shotlist_item_id", v)} /></div>
              <div><Label className="text-xs text-muted-foreground">Quality (0–1)</Label><Input type="number" step="0.05" min={0} max={1} value={a.quality_score} onChange={e => set("quality_score", Number(e.target.value))} /></div>
              <div className="flex items-end gap-2"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={a.approved} onChange={e => set("approved", e.target.checked)} className="scrub size-4" /> Approved for use</label></div>
              {a.kind !== "image" && <><div><Label className="text-xs text-muted-foreground">Usable start (s) — drag the left handle or type</Label><Input type="number" step="0.05" min={0} max={a.duration} value={a.usable_start} onChange={e => set("usable_start", Number(e.target.value))} /></div>
              <div><Label className="text-xs text-muted-foreground">Usable end (s)</Label><Input type="number" step="0.05" min={0} max={a.duration} value={a.usable_end} onChange={e => set("usable_end", Number(e.target.value))} /></div></>}
              <div className="col-span-2 flex items-center gap-2 pt-2">
                <Button type="button" variant="ghost" className="text-fail hover:text-fail" disabled={del.isPending}
                  onClick={async () => { if (await confirm({ title: "Delete this clip?", subject: `${a.id} · ${a.file}`, description: "Removed from the library and from disk. Videos already rendered with it are not affected.", confirmLabel: "Delete clip" })) del.mutate() }}>
                  <Trash2 className="size-4" /> Delete clip
                </Button>
                <span className="flex-1" />
                <Button type="button" variant="ghost" onClick={() => { setForm({}); onClose() }}>Cancel</Button>
                <Button type="submit" disabled={save.isPending || Object.keys(form).length === 0}>Save changes</Button>
              </div>
            </form>
          </div>
        </>)}
      </DialogContent>
    </Dialog>
  )
}
