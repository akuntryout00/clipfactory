import { useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Check, ChevronDown } from "lucide-react"
import { lab } from "@/lib/api"
import type { LabProvider } from "@/lib/types"
import { cn } from "@/lib/utils"

export function ProviderSelect({ value, onChange, exclude }: { value: string; onChange: (v: string) => void; exclude?: string | null }) {
  const { data } = useQuery({ queryKey: ["lab-providers"], queryFn: lab.providers })
  const rows = (data ?? []).filter(p => (p.id !== "fake" || import.meta.env.DEV) && p.id !== exclude)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", onDoc); document.addEventListener("keydown", onKey)
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey) }
  }, [open])
  const sel = rows.find(p => p.id === value)
  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen(o => !o)} aria-haspopup="listbox" aria-expanded={open}
        className={cn("flex w-full items-center gap-3 rounded-lg border bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/60 focus-visible:outline-2 focus-visible:outline-ring", open ? "border-primary" : "border-border")}>
        {sel ? <ProviderRow p={sel} /> : <span className="flex-1 text-sm text-muted-foreground">Choose a video model…</span>}
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div role="listbox" className="absolute z-50 mt-1 max-h-[340px] w-full overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-xl">
          {rows.map(p => (
            <button type="button" key={p.id} role="option" aria-selected={p.id === value} disabled={!p.available} title={p.model}
              onClick={() => { onChange(p.id); setOpen(false) }}
              className={cn("flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors",
                p.id === value ? "bg-primary/10" : "hover:bg-accent", !p.available && "cursor-not-allowed opacity-45")}>
              <ProviderRow p={p} />
              {p.id === value && <Check className="size-4 shrink-0 text-primary" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ProviderRow({ p }: { p: LabProvider }) {
  return (
    <div className="flex min-w-0 flex-1 items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold">{p.label}</div>
        <div className="font-mono text-[10px] text-muted-foreground">{p.vendor}{!p.available && p.needs ? ` · needs ${p.needs}` : ""}</div>
      </div>
      <div className="shrink-0 text-right">
        <div className="font-mono text-sm font-semibold text-primary">{p.price_per_second > 0 ? `$${p.price_per_second.toFixed(2)}` : "free"}<span className="text-[10px] font-normal text-muted-foreground">/s</span></div>
        <div className="font-mono text-[10px] text-muted-foreground">≤{p.max_seconds}s clips</div>
      </div>
    </div>
  )
}

export function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-[84px] rounded-md border border-border bg-card px-2 py-1.5">
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-heading text-sm font-semibold">{value}</div>
      {sub && <div className="truncate font-mono text-[9px] text-muted-foreground" title={sub}>{sub}</div>}
    </div>
  )
}

