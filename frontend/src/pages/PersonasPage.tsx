import { useState } from "react"
import { useQueries, useQuery } from "@tanstack/react-query"
import { Check, Pencil, Plus } from "lucide-react"
import { api } from "@/lib/api"
import { personaLabel, usePersona } from "@/lib/persona"
import type { Persona } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { PersonaEditor } from "@/components/PersonaEditor"
import { PersonaWizard } from "@/components/PersonaWizard"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export default function PersonasPage() {
  const { personas, activeId, setActiveId } = usePersona()
  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: () => api.projects(), staleTime: 30_000 })
  const { data: assets } = useQuery({ queryKey: ["assets"], queryFn: () => api.assets(), staleTime: 30_000 })
  const coverage = useQueries({ queries: personas.map(p => ({ queryKey: ["shotlist", p.id], queryFn: () => api.shotlist(p.id), staleTime: 30_000 })) })
  const [editing, setEditing] = useState<Persona | null>(null)
  const [creating, setCreating] = useState(false)
  const count = (pid: string) => ({
    projects: (projects ?? []).filter(p => p.persona_id === pid).length,
    clips: (assets ?? []).filter(a => a.persona_id === pid).length,
  })
  return (
    <div>
      <PageHeader eyebrow="Who is talking" title="Personas"
        actions={<Button onClick={() => setCreating(true)}><Plus className="size-4" /> New persona</Button>}>
        <p className="mt-1 text-sm text-muted-foreground">Each persona has its own character, voice, projects and B-roll library. The active persona (sidebar) scopes Projects, Generate and B-roll.</p>
      </PageHeader>
      <div className="grid gap-4 px-8 py-6 md:grid-cols-2">
        {personas.map(p => {
          const c = count(p.id)
          const isActive = p.id === activeId
          return (
            <Card key={p.id} className={cn(isActive && "border-primary")}>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2 font-heading">
                  <span className="flex items-center gap-2">{personaLabel(p)}{isActive && <span className="rounded bg-primary/15 px-1.5 py-0.5 font-mono text-[10px] font-normal uppercase tracking-wider text-primary">active</span>}</span>
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-[11px] font-normal text-muted-foreground">{p.id}</span>
                    {!isActive && <Button size="sm" variant="outline" onClick={() => setActiveId(p.id)}><Check className="size-3.5" /> Use</Button>}
                    <Button size="sm" variant="outline" onClick={() => setEditing(p)}><Pencil className="size-3.5" /> Edit</Button>
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p className="text-xs text-muted-foreground">{p.name}</p>
                {p.identity && <p><span className="font-semibold">{p.identity.name}</span>{p.identity.age ? `, ${p.identity.age}` : ""}{p.identity.location ? `, ${p.identity.location}` : ""}{p.identity.background ? <> — <span className="text-muted-foreground">{p.identity.background}</span></> : null}</p>}
                <p className="text-xs text-muted-foreground">Audience: {p.audience}</p>
                <Row label="pillars" items={p.topics} /><Row label="tone" items={p.tone} /><Row label="never" items={p.avoid} /><Row label="tools" items={p.tools} />
                <div className="font-mono text-[11px] text-muted-foreground">
                  products: {p.products.length ? p.products.map(x => x.name).join(", ") : "none"} ({p.product_mention_policy}) · voice {p.voice.provider}{p.voice.voice_id ? "" : " (env voice id)"} speed {p.voice.speed} · {p.speech_rate_wps} w/s · {p.target_duration}s / max {p.max_duration}s
                </div>
                <div className="border-t border-border pt-2 font-mono text-[11px] text-muted-foreground">{c.projects} projects · {c.clips} clips in <span className="text-foreground">assets/{p.id}/</span>{(() => { const cv = coverage[personas.indexOf(p)]?.data; return cv && cv.items_total > 0 ? <> · B-roll target <span className="text-foreground">{cv.percent}%</span> ({cv.filled}/{cv.wanted})</> : <> · no B-roll target yet</> })()}</div>
              </CardContent>
            </Card>
          )
        })}
        {personas.length === 0 && <p className="text-sm text-muted-foreground">No personas yet — create one to start generating.</p>}
      </div>
      <PersonaEditor persona={editing} onClose={() => setEditing(null)} />
      <PersonaWizard open={creating} onClose={() => setCreating(false)} onCreated={p => setActiveId(p.id)} />
    </div>
  )
}

function Row({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null
  return <div className="flex flex-wrap items-baseline gap-1"><span className="mr-1 font-mono text-[11px] text-primary">{label}</span>{items.map(i => <span key={i} className="rounded bg-secondary px-1.5 py-0.5 text-[11px]">{i}</span>)}</div>
}
