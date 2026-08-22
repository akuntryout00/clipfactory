import { useEffect, useMemo, useRef } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RotateCcw, Upload } from "lucide-react"
import { toast } from "sonner"
import { api, media } from "@/lib/api"
import type { CaptionOverrides, CaptionStyle, FontInfo } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"

/** Merge overrides onto a caption style the same way the backend does (later layer wins, null = keep). */
export function applyCaptionOverrides(base: CaptionStyle, ...layers: (CaptionOverrides | null | undefined)[]): CaptionStyle {
  const out: CaptionStyle = { ...base, overlay: { ...base.overlay } }
  for (const ov of layers) {
    if (!ov) continue
    if (ov.font_name) out.font_name = ov.font_name
    if (ov.font_size != null) out.font_size = ov.font_size
    if (ov.bold != null) out.bold = ov.bold
    if (ov.vertical_anchor_ratio != null) out.vertical_anchor_ratio = ov.vertical_anchor_ratio
    if (ov.overlay_font_name) out.overlay.font_name = ov.overlay_font_name
    if (ov.overlay_font_size != null) out.overlay.font_size = ov.overlay_font_size
    if (ov.overlay_vertical_anchor_ratio != null) out.overlay.vertical_anchor_ratio = ov.overlay_vertical_anchor_ratio
  }
  return out
}

const loaded = new Set<string>()
/** Load a font from the fonts folder into the browser so the preview uses the real face. System fonts (e.g. DejaVu) fall back. */
function useFontFace(fonts: FontInfo[] | undefined, family: string) {
  useEffect(() => {
    const f = fonts?.find(x => x.family === family && x.file)
    if (!f || !f.file || loaded.has(family) || typeof FontFace === "undefined") return
    const face = new FontFace(family, `url(${media.fontFile(f.file)})`)
    face.load().then(ff => { document.fonts.add(ff); loaded.add(family) }).catch(() => { /* preview falls back */ })
  }, [fonts, family])
}

const PRESETS: { label: string; ratio: number }[] = [
  { label: "Upper", ratio: 0.45 }, { label: "Middle", ratio: 0.58 }, { label: "Lower", ratio: 0.72 }, { label: "Bottom", ratio: 0.8 },
]
const OVERLAY_PRESETS: { label: string; ratio: number }[] = [
  { label: "Top", ratio: 0.2 }, { label: "Upper", ratio: 0.36 }, { label: "Middle", ratio: 0.5 },
]

type ResetProps = { scopeLabel: string }

function ResetBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return <button type="button" className="inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground hover:text-foreground" onClick={onClick}><RotateCcw className="size-3" /> {children}</button>
}

function FontSelect({ label, current, baseValue, onPick, dirFonts, sysFonts, scopeLabel }: ResetProps & { label: string; current: string | null | undefined; baseValue: string; onPick: (v: string | null) => void; dirFonts: FontInfo[]; sysFonts: FontInfo[] }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
        {current && <ResetBtn onClick={() => onPick(null)}>{scopeLabel}</ResetBtn>}
      </div>
      <select value={current ?? ""} onChange={e => onPick(e.target.value || null)} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
        <option value="">Default · {baseValue}</option>
        {dirFonts.length > 0 && <optgroup label="Fonts folder">{dirFonts.map(f => <option key={f.file} value={f.family}>{f.family}{f.style && f.style !== "Regular" ? ` ${f.style}` : ""}</option>)}</optgroup>}
        {sysFonts.length > 0 && <optgroup label="System">{sysFonts.map(f => <option key={f.family} value={f.family}>{f.family}</option>)}</optgroup>}
      </select>
    </div>
  )
}

function NumField({ label, current, baseValue, min, max, step, onPick }: { label: string; current: number | null | undefined; baseValue: number; min: number; max: number; step: number; onPick: (v: number | null) => void }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
        {current != null && <ResetBtn onClick={() => onPick(null)}>{baseValue}</ResetBtn>}
      </div>
      <Input type="number" min={min} max={max} step={step} value={current ?? baseValue} onChange={e => onPick(e.target.value === "" ? null : Number(e.target.value))} className="font-mono" />
    </div>
  )
}

function Position({ label, current, baseValue, presets, min, max, onPick }: { label: string; current: number | null | undefined; baseValue: number; presets: { label: string; ratio: number }[]; min: number; max: number; onPick: (v: number | null) => void }) {
  const v = current ?? baseValue
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <Label className="text-xs uppercase tracking-wider text-muted-foreground">{label} · <span className="font-mono text-foreground">{Math.round(v * 100)}%</span> from top</Label>
        {current != null && <ResetBtn onClick={() => onPick(null)}>{Math.round(baseValue * 100)}%</ResetBtn>}
      </div>
      <input type="range" min={min} max={max} step={0.01} value={v} onChange={e => onPick(Number(e.target.value))} className="scrub w-full" />
      <div className="mt-1 flex gap-1">
        {presets.map(pr => <button key={pr.label} type="button" onClick={() => onPick(pr.ratio)} className={cn("rounded-md border px-2 py-0.5 font-mono text-[10px]", Math.abs(v - pr.ratio) < 0.005 ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}>{pr.label}</button>)}
      </div>
    </div>
  )
}

export function CaptionSettingsForm({ base, value, onChange, scopeLabel }: {
  /** style these overrides sit on top of (template defaults, or template+global for a project) */
  base: CaptionStyle
  value: CaptionOverrides
  onChange: (v: CaptionOverrides) => void
  /** e.g. "template default" / "system setting" — shown on the reset hints */
  scopeLabel: string
}) {
  const qc = useQueryClient()
  const { data: fontsData } = useQuery({ queryKey: ["fonts"], queryFn: api.fonts, staleTime: 60_000 })
  const fonts = fontsData?.fonts
  const eff = useMemo(() => applyCaptionOverrides(base, value), [base, value])
  useFontFace(fonts, eff.font_name)
  useFontFace(fonts, eff.overlay.font_name)
  const set = (patch: CaptionOverrides) => onChange({ ...value, ...patch })
  const fileRef = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: (f: File) => api.uploadFont(f),
    onSuccess: f => { toast.success(`Font ${f.family} added`); qc.invalidateQueries({ queryKey: ["fonts"] }) },
    onError: e => toast.error(e.message),
  })
  const dirFonts = (fonts ?? []).filter(f => f.source === "fonts_dir")
  const sysFonts = (fonts ?? []).filter(f => f.source === "system")

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_260px]">
      <div className="space-y-6">
        <section className="space-y-3">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">Captions (spoken words)</h3>
          <div className="grid gap-3 sm:grid-cols-[1fr_120px_110px]">
            <FontSelect label="Font" current={value.font_name} baseValue={base.font_name} onPick={v => set({ font_name: v })} dirFonts={dirFonts} sysFonts={sysFonts} scopeLabel={scopeLabel} />
            <NumField label="Size" current={value.font_size} baseValue={base.font_size} min={30} max={160} step={2} onPick={v => set({ font_size: v })} />
            <div>
              <div className="mb-1 flex items-center justify-between">
                <Label className="text-xs uppercase tracking-wider text-muted-foreground">Weight</Label>
                {value.bold != null && <ResetBtn onClick={() => set({ bold: null })}>{base.bold ? "bold" : "regular"}</ResetBtn>}
              </div>
              <select value={value.bold == null ? "" : value.bold ? "bold" : "regular"} onChange={e => set({ bold: e.target.value === "" ? null : e.target.value === "bold" })} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
                <option value="">Default · {base.bold ? "bold" : "regular"}</option><option value="bold">Bold</option><option value="regular">Regular</option>
              </select>
            </div>
          </div>
          <Position label="Vertical position" current={value.vertical_anchor_ratio} baseValue={base.vertical_anchor_ratio} presets={PRESETS} min={0.3} max={0.9} onPick={v => set({ vertical_anchor_ratio: v })} />
        </section>
        <section className="space-y-3">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">Text overlays (big keywords)</h3>
          <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
            <FontSelect label="Font" current={value.overlay_font_name} baseValue={base.overlay.font_name} onPick={v => set({ overlay_font_name: v })} dirFonts={dirFonts} sysFonts={sysFonts} scopeLabel={scopeLabel} />
            <NumField label="Size" current={value.overlay_font_size} baseValue={base.overlay.font_size} min={30} max={200} step={2} onPick={v => set({ overlay_font_size: v })} />
          </div>
          <Position label="Vertical position" current={value.overlay_vertical_anchor_ratio} baseValue={base.overlay.vertical_anchor_ratio} presets={OVERLAY_PRESETS} min={0.08} max={0.7} onPick={v => set({ overlay_vertical_anchor_ratio: v })} />
        </section>
        <div className="flex items-center gap-3 border-t border-border pt-3 text-xs text-muted-foreground">
          <input ref={fileRef} type="file" accept=".ttf,.otf" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = "" }} />
          <Button type="button" size="sm" variant="outline" onClick={() => fileRef.current?.click()} disabled={upload.isPending}><Upload className="size-3.5" /> {upload.isPending ? "Uploading…" : "Add font (.ttf/.otf)"}</Button>
          <span>Goes to <code className="font-mono">{fontsData?.fonts_dir ?? "fonts/"}</code> · {dirFonts.length} in folder · {sysFonts.length} system</span>
        </div>
      </div>
      <CaptionPreview style={eff} />
    </div>
  )
}

/** 9:16 frame with safe zones, one caption chunk and one overlay at their vertical anchors (text scaled 1080 → preview width). */
export function CaptionPreview({ style }: { style: CaptionStyle }) {
  const W = 234, H = 416, k = W / 1080
  const sz = style.safe_zone
  return (
    <div>
      <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Preview</div>
      <div className="relative overflow-hidden rounded-md border border-border bg-[#15171b]" style={{ width: W, height: H, backgroundImage: "linear-gradient(160deg,#2a2d34 0%,#15171b 60%,#0e0f12 100%)" }}>
        <div className="absolute inset-x-0 top-0 border-b border-dashed border-fail/40" style={{ height: H * sz.top }} />
        <div className="absolute inset-x-0 bottom-0 border-t border-dashed border-fail/40" style={{ height: H * sz.bottom }} />
        <div className="absolute inset-y-0 right-0 border-l border-dashed border-fail/40" style={{ width: W * sz.right }} />
        <div className="absolute inset-y-0 left-0 border-r border-dashed border-fail/40" style={{ width: W * sz.left }} />
        <div className="absolute left-0 right-0 flex justify-center px-2 text-center" style={{ top: H * style.overlay.vertical_anchor_ratio, transform: "translateY(-100%)" }}>
          <span style={{ fontFamily: `"${style.overlay.font_name}", "DejaVu Sans", sans-serif`, fontSize: style.overlay.font_size * k, fontWeight: style.overlay.bold ? 700 : 400, color: "#fff", lineHeight: 1.05, letterSpacing: 0.5, WebkitTextStroke: `${Math.max(1, style.overlay.outline * k * 0.8)}px #000`, paintOrder: "stroke fill" }}>ONE THING</span>
        </div>
        <div className="absolute left-0 right-0 flex justify-center px-2 text-center" style={{ top: H * style.vertical_anchor_ratio, transform: "translateY(-100%)" }}>
          <span style={{ fontFamily: `"${style.font_name}", "DejaVu Sans", sans-serif`, fontSize: style.font_size * k, fontWeight: style.bold ? 700 : 400, color: "#fff", lineHeight: 1.1, WebkitTextStroke: `${Math.max(1, style.outline * k * 0.8)}px #000`, paintOrder: "stroke fill" }}>you opened <span style={{ color: "#FFE500" }}>your laptop</span></span>
        </div>
      </div>
      <p className="mt-1 w-[234px] text-[11px] text-muted-foreground">Dashed = TikTok safe zones. Font: <span className="font-mono">{style.font_name}</span> {style.font_size}px · overlay <span className="font-mono">{style.overlay.font_name}</span> {style.overlay.font_size}px</p>
    </div>
  )
}
