import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FolderInput, Sparkles, Trash2, Upload } from "lucide-react"
import { toast } from "sonner"
import { api, media } from "@/lib/api"
import type { Asset } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { RangeTrimmer } from "@/components/RangeTrimmer"

export default function AssetsPage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ["assets"], queryFn: api.assets })
  const [q, setQ] = useState("")
  const [cat, setCat] = useState("ALL")
  const [edit, setEdit] = useState<Asset | null>(null)
  const [adding, setAdding] = useState(false)
  const imp = useMutation({ mutationFn: api.importAssets, onSuccess: r => { toast.success(`Imported: ${r.created} new, ${r.updated} refreshed`); qc.invalidateQueries({ queryKey: ["assets"] }) }, onError: e => toast.error(e.message) })
  const enrich = useMutation({ mutationFn: api.enrichAssets, onSuccess: r => { toast.success(`Enriched ${r.enriched} clips`); qc.invalidateQueries({ queryKey: ["assets"] }) }, onError: e => toast.error(e.message) })
  const cats = useMemo(() => Array.from(new Set((data ?? []).map(a => a.file.split("/")[0]))).sort(), [data])
  const rows = useMemo(() => (data ?? []).filter(a => (cat === "ALL" || a.file.startsWith(cat + "/")) &&
    (!q || [a.id, a.file, a.description, a.action, a.location, a.mood, ...(a.tags ?? [])].join(" ").toLowerCase().includes(q.toLowerCase()))), [data, q, cat])
  const approved = (data ?? []).filter(a => a.approved).length

  return (
    <div>
      <PageHeader eyebrow="Asset library" title="B-roll"
        actions={<>
          <Button size="sm" onClick={() => setAdding(true)}><Upload className="size-4" /> Add video</Button>
          <Button variant="outline" size="sm" onClick={() => imp.mutate()} disabled={imp.isPending}><FolderInput className="size-4" /> {imp.isPending ? "Importing…" : "Import folder"}</Button>
          <Button variant="outline" size="sm" onClick={() => enrich.mutate()} disabled={enrich.isPending}><Sparkles className="size-4" /> {enrich.isPending ? "Enriching…" : "Enrich with AI"}</Button>
        </>}>
        <p className="mt-1 text-sm text-muted-foreground">{data?.length ?? 0} clips · {approved} approved · drop new files into <code className="font-mono">assets/&lt;category&gt;/</code> then Import.</p>
      </PageHeader>
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
              <span className="absolute right-1 top-1 rounded bg-background/80 px-1 font-mono text-[10px]">{a.duration.toFixed(1)}s</span>
              {!a.approved && <span className="absolute bottom-1 left-1 rounded bg-fail/80 px-1 font-mono text-[10px] text-background">not approved</span>}
              {a.usage_count > 0 && <span className="absolute bottom-1 right-1 rounded bg-background/80 px-1 font-mono text-[10px]">×{a.usage_count}</span>}
            </div>
            <div className="mt-1 truncate font-mono text-[11px]">{a.file.split("/").pop()}</div>
            <div className="truncate text-[11px] text-muted-foreground">{a.action} · {a.shot} · q{a.quality_score.toFixed(2)}</div>
          </button>
        ))}
      </div>
      <AssetDialog asset={edit} onClose={() => setEdit(null)} />
      <UploadDialog open={adding} onClose={() => setAdding(false)} categories={cats} />
    </div>
  )
}

function UploadDialog({ open, onClose, categories }: { open: boolean; onClose: () => void; categories: string[] }) {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [category, setCategory] = useState(categories[0] ?? "desk")
  const [newCat, setNewCat] = useState("")
  const [description, setDescription] = useState("")
  const [tags, setTags] = useState("")
  const [approved, setApproved] = useState(true)
  const [pct, setPct] = useState(0)
  const [range, setRange] = useState<{ s: number; e: number; dur: number } | null>(null)
  const cat = category === "__new__" ? newCat.trim().toLowerCase() : category
  const reset = () => { setFile(null); setDescription(""); setTags(""); setPct(0); setNewCat(""); setRange(null) }
  const up = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append("file", file!); fd.append("category", cat); fd.append("description", description); fd.append("tags", tags); fd.append("approved", String(approved))
      if (range) { fd.append("usable_start", String(range.s)); fd.append("usable_end", String(range.e)) }
      return api.uploadAsset(fd, setPct)
    },
    onSuccess: a => {
      if (a.enriched) toast.success(`Added ${a.id} · AI tags added (${a.tags.length} tags)`)
      else toast.warning(`Added ${a.id} — AI enrichment skipped${a.enrichError ? `: ${a.enrichError}` : ""}`)
      qc.invalidateQueries({ queryKey: ["assets"] }); reset(); onClose()
    },
    onError: e => toast.error(e.message),
  })
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file])
  return (
    <Dialog open={open} onOpenChange={o => { if (!o) { reset(); onClose() } }}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader><DialogTitle className="font-heading">Add a B-roll clip</DialogTitle></DialogHeader>
        <form className="grid gap-4 md:grid-cols-[300px_1fr]" onSubmit={e => { e.preventDefault(); if (file && cat) up.mutate() }}>
          <div>
            {previewUrl ? (
              <RangeTrimmer src={previewUrl} duration={range?.dur ?? 0} start={range?.s ?? 0} end={range?.e ?? 0}
                onChange={(s, e) => setRange(r => ({ s, e, dur: r?.dur ?? e }))} />
            ) : (
              <label className="block aspect-[9/16] cursor-pointer overflow-hidden rounded-md border border-dashed border-border bg-surface-2 hover:border-primary">
                <span className="grid h-full place-items-center p-4 text-center text-xs text-muted-foreground">Click to choose a video<br />(.mp4 / .mov, vertical 9:16 preferred)</span>
                <input type="file" accept="video/mp4,video/quicktime,.mp4,.mov,.m4v" className="sr-only" onChange={e => setFile(e.target.files?.[0] ?? null)} />
              </label>
            )}
            {/* hidden probe to learn the duration and seed the range to whole clip minus small margins */}
            {previewUrl && !range && <video src={previewUrl} className="hidden" preload="metadata"
              onLoadedMetadata={e => { const d = e.currentTarget.duration; const m = Math.min(0.2, d * 0.05); setRange({ s: Math.round(m * 20) / 20, e: Math.round((d - m) * 20) / 20, dur: d }) }} />}
            {file && <div className="mt-1 flex items-center justify-between gap-2 font-mono text-[11px] text-muted-foreground">
              <span className="truncate">{file.name} · {(file.size / 1e6).toFixed(1)} MB</span>
              <button type="button" className="text-primary underline" onClick={() => { setFile(null); setRange(null) }}>change file</button>
            </div>}
          </div>
          <div className="grid content-start gap-3 text-sm">
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
            <label className="flex items-center gap-2"><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} className="scrub size-4" /> Approved for use right away</label>
            {up.isPending && <div className="h-1.5 overflow-hidden rounded bg-surface-2"><div className="h-full bg-primary transition-[width]" style={{ width: `${pct}%` }} /></div>}
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="ghost" onClick={() => { reset(); onClose() }}>Cancel</Button>
              <Button type="submit" disabled={!file || !cat || up.isPending}>{up.isPending ? (pct < 100 ? `Uploading ${pct}%` : "Analyzing with AI…") : "Upload clip"}</Button>
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
  const [form, setForm] = useState<Partial<Asset>>({})
  const a = asset ? { ...asset, ...form } : null
  const save = useMutation({
    mutationFn: () => api.patchAsset(asset!.id, form),
    onSuccess: () => { toast.success("Saved"); qc.invalidateQueries({ queryKey: ["assets"] }); setForm({}); onClose() },
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
              <RangeTrimmer src={media.assetFile(a.id)} duration={a.duration} start={a.usable_start} end={a.usable_end}
                onChange={(s, e) => setForm(f => ({ ...f, usable_start: s, usable_end: e }))} />
              <div className="font-mono text-[11px] text-muted-foreground">{a.width}×{a.height} · {a.fps?.toFixed(2)} fps · {a.duration.toFixed(2)}s · used ×{a.usage_count}</div>
            </div>
            <form className="grid grid-cols-2 content-start gap-3 text-sm" onSubmit={e => { e.preventDefault(); save.mutate() }}>
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
              <div><Label className="text-xs text-muted-foreground">Quality (0–1)</Label><Input type="number" step="0.05" min={0} max={1} value={a.quality_score} onChange={e => set("quality_score", Number(e.target.value))} /></div>
              <div className="flex items-end gap-2"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={a.approved} onChange={e => set("approved", e.target.checked)} className="scrub size-4" /> Approved for use</label></div>
              <div><Label className="text-xs text-muted-foreground">Usable start (s) — drag the left handle or type</Label><Input type="number" step="0.05" min={0} max={a.duration} value={a.usable_start} onChange={e => set("usable_start", Number(e.target.value))} /></div>
              <div><Label className="text-xs text-muted-foreground">Usable end (s)</Label><Input type="number" step="0.05" min={0} max={a.duration} value={a.usable_end} onChange={e => set("usable_end", Number(e.target.value))} /></div>
              <div className="col-span-2 flex items-center gap-2 pt-2">
                <Button type="button" variant="ghost" className="text-fail hover:text-fail" disabled={del.isPending}
                  onClick={() => { if (confirm(`Delete ${a.id} (${a.file}) from the library and disk? Existing renders are not affected.`)) del.mutate() }}>
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
