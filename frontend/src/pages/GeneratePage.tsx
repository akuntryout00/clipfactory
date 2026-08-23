import { useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Sparkles } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { usePersona } from "@/lib/persona"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

export default function GeneratePage() {
  const nav = useNavigate()
  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: api.templates })
  const { personas, activeId, setActiveId } = usePersona()
  const [params] = useSearchParams()
  const [templateId, setTemplateId] = useState(params.get("template") || "story_v1")
  const [topic, setTopic] = useState(params.get("topic") || "")
  const [duration, setDuration] = useState(18)
  const [personaId, setPersonaId] = useState(activeId)
  useEffect(() => { setPersonaId(activeId) }, [activeId])
  const persona = personas.find(p => p.id === personaId)
  const tpl = templates?.find(t => t.id === templateId)

  const create = useMutation({
    mutationFn: async () => {
      const p = await api.createProject({ topic: topic.trim(), template_id: templateId, target_duration: duration, persona_id: personaId })
      await api.action(p.id, "generate")
      return p
    },
    onSuccess: p => { toast.success("Generation started"); if (personaId !== activeId) setActiveId(personaId); nav(`/projects/${p.id}`) },
    onError: e => toast.error(e.message),
  })

  return (
    <div>
      <PageHeader eyebrow="New video" title="Generate">
        <p className="mt-1 text-sm text-muted-foreground">Give it a topic and a template. Script, voice, scenes, B-roll, captions and render run in the background.</p>
      </PageHeader>
      <div className="grid gap-6 px-8 py-6 lg:grid-cols-[1fr_340px]">
        <form noValidate className="space-y-6" onSubmit={e => { e.preventDefault(); if (topic.trim().length >= 3) create.mutate() }}>
          <div>
            <Label htmlFor="persona" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Persona</Label>
            <select id="persona" value={personaId} onChange={e => setPersonaId(e.target.value)} className="h-9 w-full max-w-md rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-2 focus-visible:outline-ring">
              {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <p className="mt-1 text-xs text-muted-foreground">The script is written in this character's voice and B-roll comes from their own library.</p>
          </div>
          <div>
            <Label className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Template</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {(templates ?? []).map(t => (
                <button type="button" key={t.id} onClick={() => { setTemplateId(t.id); setDuration(t.duration.target) }}
                  className={cn("rounded-md border p-3 text-left transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                    templateId === t.id ? "border-primary bg-primary/5" : "border-border bg-card")}>
                  <div className="flex items-baseline justify-between">
                    <span className="font-heading font-semibold">{t.name}{t.kind === "slideshow" && <span className="ml-2 rounded bg-primary/15 px-1.5 py-0.5 font-mono text-[10px] font-normal uppercase tracking-wider text-primary">photo slideshow</span>}</span>
                    <span className="font-mono text-[11px] text-muted-foreground">{t.id}</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{t.description}</p>
                  <p className="mt-2 font-mono text-[11px] text-muted-foreground">{t.sections.map(s => s.type).join(" → ")}</p>
                </button>
              ))}
            </div>
          </div>
          <div>
            <Label htmlFor="topic" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Topic</Label>
            <Textarea id="topic" value={topic} onChange={e => setTopic(e.target.value)} rows={3}
              placeholder={templateId === "pov_v1" ? "POV: you opened your laptop just to check one thing" : "Why I stopped answering Slack in the morning"} />
            <p className="mt-1 text-xs text-muted-foreground">{tpl?.kind === "slideshow" ? "Slideshow: one bold line per photo, no voice-over — photos come from this persona's Photos library (B-roll → Photos); add a trending sound when you post." : "Write it the way the hook could sound. First person works best for this persona."}</p>
          </div>
          <div>
            <Label htmlFor="dur" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Target length · <span className="font-mono text-foreground">{duration}s</span></Label>
            <input id="dur" type="range" min={15} max={25} step={1} value={duration} onChange={e => setDuration(Number(e.target.value))} className="scrub w-full" />
            <div className="flex justify-between font-mono text-[11px] text-muted-foreground"><span>15s</span><span>{tpl ? `template ${tpl.duration.min}–${tpl.duration.max}s` : ""}</span><span>25s</span></div>
            {tpl && duration > tpl.duration.max && <p className="mt-1 text-xs text-muted-foreground">Above the template's usual {tpl.duration.max}s — allowed; the voice may run up to {duration + 1}s.</p>}
          </div>
          <Button type="submit" size="lg" disabled={topic.trim().length < 3 || !personaId || create.isPending}>
            <Sparkles className="size-4" /> {create.isPending ? "Starting…" : "Generate video"}
          </Button>
        </form>
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-sm">Persona</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {persona ? (<>
                <div className="font-heading text-lg font-semibold">{persona.identity?.name ?? persona.name}</div>
                <p className="text-muted-foreground">{persona.identity?.background ?? persona.audience}</p>
                <div className="flex flex-wrap gap-1 pt-1">{persona.tone.map(t => <span key={t} className="rounded bg-secondary px-1.5 py-0.5 text-[11px]">{t}</span>)}</div>
                <p className="pt-1 font-mono text-[11px] text-muted-foreground">voice {persona.voice.provider} · {persona.speech_rate_wps} words/s · B-roll assets/{persona.id}/</p>
              </>) : <p className="text-muted-foreground">Loading…</p>}
            </CardContent>
          </Card>
          {tpl && (
            <Card>
              <CardHeader><CardTitle className="text-sm">{tpl.name} structure</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm">
                <ol className="space-y-1">
                  {tpl.sections.map(s => (
                    <li key={s.type} className="flex gap-2"><span className="w-24 shrink-0 font-mono text-[11px] text-primary">{s.type}</span><span className="text-xs text-muted-foreground">{s.guidance} <span className="opacity-60">({Math.round(s.weight * 100)}%)</span></span></li>
                  ))}
                </ol>
                {tpl.closing && <p className="border-t border-border pt-2 text-xs text-muted-foreground"><span className="font-mono text-primary">closing</span> {tpl.closing}</p>}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
