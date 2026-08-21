import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { PageHeader } from "@/components/PageHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function TemplatesPage() {
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: api.templates })
  const { data: personas } = useQuery({ queryKey: ["personas"], queryFn: api.personas })
  return (
    <div>
      <PageHeader eyebrow="Configuration" title="Templates & persona">
        <p className="mt-1 text-sm text-muted-foreground">Read-only view of <code className="font-mono">configs/</code>. Edit the JSON files to change structure, weights, closings or persona rules — no code changes needed.</p>
      </PageHeader>
      <div className="space-y-8 px-8 py-6">
        <section className="grid gap-4 md:grid-cols-2">
          {(templates ?? []).map(t => (
            <Card key={t.id}>
              <CardHeader><CardTitle className="flex items-baseline justify-between font-heading"><span>{t.name}</span><span className="font-mono text-[11px] font-normal text-muted-foreground">{t.id}</span></CardTitle></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <p className="text-muted-foreground">{t.description}</p>
                <div className="flex h-2 overflow-hidden rounded bg-surface-2">
                  {t.sections.map((s, i) => <div key={s.type} style={{ width: `${s.weight * 100}%` }} className={i % 2 ? "bg-primary/40" : "bg-primary/70"} title={`${s.type} ${Math.round(s.weight * 100)}%`} />)}
                </div>
                <ol className="space-y-1">{t.sections.map(s => <li key={s.type} className="flex gap-2"><span className="w-28 shrink-0 font-mono text-[11px] text-primary">{s.type} <span className="text-muted-foreground">{Math.round(s.weight * 100)}%</span></span><span className="text-xs text-muted-foreground">{s.guidance}</span></li>)}</ol>
                <div className="grid grid-cols-3 gap-2 border-t border-border pt-2 font-mono text-[11px] text-muted-foreground">
                  <span>{t.duration.min}–{t.duration.max}s (target {t.duration.target})</span><span>shots {t.shot_duration.min}–{t.shot_duration.max}s</span><span>overlays {t.overlays.min}–{t.overlays.max}</span>
                  <span>captions {t.caption_style}</span><span>music {t.music_category ?? "—"}</span><span>voiceover {t.voiceover ? "yes" : "optional"}</span>
                </div>
                {t.closing && <p className="text-xs"><span className="font-mono text-primary">closing</span> <span className="text-muted-foreground">{t.closing}</span></p>}
              </CardContent>
            </Card>
          ))}
        </section>
        <section className="grid gap-4 md:grid-cols-2">
          {(personas ?? []).map(p => (
            <Card key={p.id}>
              <CardHeader><CardTitle className="flex items-baseline justify-between font-heading"><span>{p.name}</span><span className="font-mono text-[11px] font-normal text-muted-foreground">{p.id}</span></CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                {p.identity && <p><span className="font-semibold">{p.identity.name}</span>{p.identity.age ? `, ${p.identity.age}` : ""}{p.identity.location ? `, ${p.identity.location}` : ""} — <span className="text-muted-foreground">{p.identity.background}</span></p>}
                <p className="text-xs text-muted-foreground">Audience: {p.audience}</p>
                <Row label="pillars" items={p.topics} /><Row label="tone" items={p.tone} /><Row label="never" items={p.avoid} /><Row label="tools" items={p.tools} />
                <div className="font-mono text-[11px] text-muted-foreground">products: {p.products.length ? p.products.map(x => x.name).join(", ") : "none"} ({p.product_mention_policy}) · voice {p.voice.provider} speed {p.voice.speed} stability {p.voice.stability} · {p.speech_rate_wps} w/s · {p.target_duration}s / max {p.max_duration}s</div>
              </CardContent>
            </Card>
          ))}
        </section>
      </div>
    </div>
  )
}
function Row({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null
  return <div className="flex flex-wrap items-baseline gap-1"><span className="mr-1 font-mono text-[11px] text-primary">{label}</span>{items.map(i => <span key={i} className="rounded bg-secondary px-1.5 py-0.5 text-[11px]">{i}</span>)}</div>
}
