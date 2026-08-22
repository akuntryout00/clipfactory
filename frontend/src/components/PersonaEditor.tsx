import { useEffect, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { ClosingStyle, Persona, ProductPolicy } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useConfirm } from "@/components/ConfirmDialog"

export const EMPTY_PERSONA: Persona = {
  id: "", name: "", language: "en-US", audience: "", topics: [], tone: [], avoid: [],
  identity: { name: "", age: null, location: "", background: "", speaks_as: "first person ('I'), talking to one viewer ('you')" },
  tools: [], products: [], product_mention_policy: "never", closing_style: "punchline_no_cta",
  target_duration: 18, max_duration: 25, speech_rate_wps: 2.5,
  voice: { provider: "elevenlabs", voice_id: "", model_id: "eleven_multilingual_v2", speed: 1.0, stability: 0.5, similarity_boost: 0.75, style: 0 },
  default_music_category: null,
}

const POLICIES: { v: ProductPolicy; l: string }[] = [
  { v: "never", l: "Never mention products" },
  { v: "occasional_soft", l: "Occasional, soft mention" },
  { v: "problem_solution_only", l: "Only when the topic is the problem they solve" },
]
const CLOSINGS: { v: ClosingStyle; l: string }[] = [
  { v: "punchline_no_cta", l: "Punchline, no call to action" },
  { v: "question", l: "End on a question" },
  { v: "soft_follow", l: "Soft follow prompt" },
]

const splitLines = (s: string) => s.split(/\n/).map(x => x.trim()).filter(Boolean)

/** Edit an existing persona in a dialog (stored in the database via /personas). New personas are created by the PersonaWizard. */
export function PersonaEditor({ persona, onClose }: { persona: Persona | null; onClose: () => void }) {
  return (
    <Dialog open={persona !== null} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="font-heading">Edit persona <span className="font-mono text-sm font-normal text-muted-foreground">· {persona?.id}</span></DialogTitle>
          <DialogDescription>Who speaks in the videos. This persona owns its own projects and B-roll library (<code className="font-mono">assets/{persona?.id}/…</code>).</DialogDescription>
        </DialogHeader>
        {persona && <PersonaForm initial={persona} mode="edit" onDone={onClose} onCancel={onClose} />}
      </DialogContent>
    </Dialog>
  )
}

/**
 * The persona fields + save/delete actions. `mode="create"` posts a new persona (id/display name come from the draft),
 * `mode="edit"` updates an existing one. Id and display name are system-managed and not shown.
 */
export function PersonaForm({ initial, mode, onDone, onCancel, submitLabel }: {
  initial: Persona; mode: "create" | "edit"; onDone: (p: Persona) => void; onCancel: () => void; submitLabel?: string
}) {
  const qc = useQueryClient()
  const confirm = useConfirm()
  const isNew = mode === "create"
  const [p, setP] = useState<Persona>(initial)
  // list fields are edited as free text (one per line) and parsed on save
  const [lists, setLists] = useState({ topics: "", tone: "", avoid: "", tools: "" })
  useEffect(() => {
    const src = structuredClone(initial)
    if (!src.identity) src.identity = { ...EMPTY_PERSONA.identity! }
    setP(src)
    setLists({ topics: src.topics.join("\n"), tone: src.tone.join("\n"), avoid: src.avoid.join("\n"), tools: src.tools.join("\n") })
  }, [initial])

  const built = (): Persona => ({
    ...p,
    id: p.id.trim(),
    name: (p.name.trim() || p.identity?.name?.trim() || p.id).slice(0, 128),
    topics: splitLines(lists.topics), tone: splitLines(lists.tone), avoid: splitLines(lists.avoid), tools: splitLines(lists.tools),
    identity: p.identity?.name?.trim() ? { ...p.identity, name: p.identity.name.trim(), age: p.identity.age || null } : null,
    products: p.products.filter(x => x.name.trim()),
    default_music_category: p.default_music_category || null,
  })
  const idOk = /^[a-z0-9][a-z0-9_-]{1,40}$/.test(p.id)
  const durOk = p.target_duration > 0 && p.target_duration <= p.max_duration
  const valid = idOk && (p.identity?.name?.trim().length ?? 0) > 0 && p.audience.trim().length > 0 && splitLines(lists.topics).length > 0 && splitLines(lists.tone).length > 0 && durOk && p.speech_rate_wps > 0

  const invalidate = () => { qc.invalidateQueries({ queryKey: ["personas"] }) }
  const save = useMutation({
    mutationFn: () => (isNew ? api.createPersona(built()) : api.updatePersona(built())),
    onSuccess: saved => { toast.success(isNew ? `Persona ${saved.identity?.name ?? saved.id} created` : `Persona ${p.id} saved`); invalidate(); onDone(saved) },
    onError: e => toast.error(e.message),
  })
  const del = useMutation({
    mutationFn: () => api.deletePersona(p.id),
    onSuccess: () => { toast.success(`Persona ${p.id} deleted`); invalidate(); onCancel() },
    onError: e => toast.error(e.message),
  })
  const setId = (id: Partial<NonNullable<Persona["identity"]>>) => setP(x => ({ ...x, identity: { ...(x.identity ?? EMPTY_PERSONA.identity!), ...id } }))
  const setVoice = (v: Partial<Persona["voice"]>) => setP(x => ({ ...x, voice: { ...x.voice, ...v } }))
  const setProduct = (i: number, patch: Partial<Persona["products"][number]>) => setP(x => ({ ...x, products: x.products.map((pr, j) => (j === i ? { ...pr, ...patch } : pr)) }))

  return (
        <form className="space-y-6" onSubmit={e => { e.preventDefault(); if (valid) save.mutate() }}>
          <Section title="Identity">
            <div className="grid gap-3 sm:grid-cols-[1fr_90px_1fr_120px]">
              <Field label="Name" hint={`id ${p.id} · set automatically`}><Input value={p.identity?.name ?? ""} onChange={e => setId({ name: e.target.value })} placeholder="Michael" /></Field>
              <Field label="Age"><Input type="number" min={0} value={p.identity?.age ?? ""} onChange={e => setId({ age: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
              <Field label="Location"><Input value={p.identity?.location ?? ""} onChange={e => setId({ location: e.target.value })} placeholder="US" /></Field>
              <Field label="Language"><Input value={p.language} onChange={e => setP(x => ({ ...x, language: e.target.value }))} className="font-mono" /></Field>
            </div>
            <Field label="Background / career" hint="fed to the script model as who is talking">
              <Textarea rows={2} value={p.identity?.background ?? ""} onChange={e => setId({ background: e.target.value })} placeholder="Ex-software engineer and CTO, 3 years indie hacker, 2 years solopreneur." />
            </Field>
            <Field label="Speaks as"><Input value={p.identity?.speaks_as ?? ""} onChange={e => setId({ speaks_as: e.target.value })} /></Field>
          </Section>

          <Section title="Content">
            <Field label="Audience" hint="who is watching"><Input value={p.audience} onChange={e => setP(x => ({ ...x, audience: e.target.value }))} placeholder="Builders and knowledge workers who want to get more done" /></Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Topic pillars" hint="one per line"><Textarea rows={4} value={lists.topics} onChange={e => setLists(l => ({ ...l, topics: e.target.value }))} placeholder={"productivity & focus\nAI workflows\nindie hacking"} /></Field>
              <Field label="Tone" hint="one per line"><Textarea rows={4} value={lists.tone} onChange={e => setLists(l => ({ ...l, tone: e.target.value }))} placeholder={"energetic\nmotivating\ndirect"} /></Field>
              <Field label="Never do" hint="one per line"><Textarea rows={3} value={lists.avoid} onChange={e => setLists(l => ({ ...l, avoid: e.target.value }))} placeholder={"hype words\nclickbait"} /></Field>
              <Field label="Tools they use" hint="one per line; the script may mention these"><Textarea rows={3} value={lists.tools} onChange={e => setLists(l => ({ ...l, tools: e.target.value }))} placeholder={"ChatGPT\nNotion"} /></Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Closing style">
                <select value={p.closing_style} onChange={e => setP(x => ({ ...x, closing_style: e.target.value as ClosingStyle }))} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
                  {CLOSINGS.map(c => <option key={c.v} value={c.v}>{c.l}</option>)}
                </select>
              </Field>
              <Field label="Product mentions">
                <select value={p.product_mention_policy} onChange={e => setP(x => ({ ...x, product_mention_policy: e.target.value as ProductPolicy }))} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
                  {POLICIES.map(c => <option key={c.v} value={c.v}>{c.l}</option>)}
                </select>
              </Field>
            </div>
            <div>
              <div className="mb-1 flex items-center justify-between">
                <Label className="text-xs uppercase tracking-wider text-muted-foreground">Products</Label>
                <Button type="button" size="sm" variant="outline" onClick={() => setP(x => ({ ...x, products: [...x.products, { name: "", one_liner: "" }] }))}><Plus className="size-3.5" /> Add product</Button>
              </div>
              {p.products.length === 0 && <p className="text-xs text-muted-foreground">None — with “Never mention products” this list is ignored anyway.</p>}
              <div className="space-y-2">
                {p.products.map((pr, i) => (
                  <div key={i} className="grid gap-2 sm:grid-cols-[200px_1fr_auto]">
                    <Input value={pr.name} onChange={e => setProduct(i, { name: e.target.value })} placeholder="Name" />
                    <Input value={pr.one_liner} onChange={e => setProduct(i, { one_liner: e.target.value })} placeholder="One-liner: what it does" />
                    <Button type="button" size="icon" variant="ghost" aria-label="Remove product" onClick={() => setP(x => ({ ...x, products: x.products.filter((_, j) => j !== i) }))}><Trash2 className="size-4" /></Button>
                  </div>
                ))}
              </div>
            </div>
          </Section>

          <Section title="Voice & pacing">
            <div className="grid gap-3 sm:grid-cols-[120px_1fr_1fr]">
              <Field label="Provider"><Input value={p.voice.provider} onChange={e => setVoice({ provider: e.target.value })} className="font-mono" /></Field>
              <Field label="Voice id" hint="ElevenLabs voice; empty = ELEVENLABS_VOICE_ID from .env"><Input value={p.voice.voice_id} onChange={e => setVoice({ voice_id: e.target.value })} className="font-mono" placeholder="21m00Tcm4TlvDq8ikWAM" /></Field>
              <Field label="Model id"><Input value={p.voice.model_id} onChange={e => setVoice({ model_id: e.target.value })} className="font-mono" /></Field>
            </div>
            <div className="grid gap-3 sm:grid-cols-4">
              <Num label="Speed" value={p.voice.speed} step={0.05} min={0.5} max={1.5} onChange={v => setVoice({ speed: v })} />
              <Num label="Stability" value={p.voice.stability} step={0.05} min={0} max={1} onChange={v => setVoice({ stability: v })} />
              <Num label="Similarity" value={p.voice.similarity_boost} step={0.05} min={0} max={1} onChange={v => setVoice({ similarity_boost: v })} />
              <Num label="Style" value={p.voice.style} step={0.05} min={0} max={1} onChange={v => setVoice({ style: v })} />
            </div>
            <div className="grid gap-3 sm:grid-cols-4">
              <Num label="Words / second" hint="measured speech rate; sizes the script" value={p.speech_rate_wps} step={0.1} min={1} max={5} onChange={v => setP(x => ({ ...x, speech_rate_wps: v }))} />
              <Num label="Target length (s)" value={p.target_duration} step={1} min={5} max={60} onChange={v => setP(x => ({ ...x, target_duration: v }))} />
              <Num label="Max length (s)" value={p.max_duration} step={1} min={5} max={60} onChange={v => setP(x => ({ ...x, max_duration: v }))} />
              <Field label="Music category" hint="optional default"><Input value={p.default_music_category ?? ""} onChange={e => setP(x => ({ ...x, default_music_category: e.target.value || null }))} className="font-mono" placeholder="upbeat" /></Field>
            </div>
            {!durOk && <p className="text-xs text-fail">Target length must be ≤ max length.</p>}
          </Section>

          <div className="flex items-center justify-between gap-2 border-t border-border pt-4">
            {!isNew ? (
              <Button type="button" variant="ghost" className="text-fail hover:text-fail" disabled={del.isPending}
                onClick={async () => { if (await confirm({ title: "Delete this persona?", subject: `${p.name} · ${p.id}`, description: "Only possible while it owns no projects or B-roll clips. Its settings are removed from the database.", confirmLabel: "Delete persona" })) del.mutate() }}>
                <Trash2 className="size-4" /> Delete
              </Button>
            ) : <span />}
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={onCancel}>{isNew ? "Back" : "Cancel"}</Button>
              <Button type="submit" disabled={!valid || save.isPending}>{save.isPending ? "Saving…" : submitLabel ?? (isNew ? "Create persona" : "Save changes")}</Button>
            </div>
          </div>
        </form>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">{title}</h3>
      {children}
    </section>
  )
}
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}
function Num({ label, hint, value, onChange, step, min, max }: { label: string; hint?: string; value: number; onChange: (v: number) => void; step: number; min: number; max: number }) {
  return (
    <Field label={label} hint={hint}>
      <Input type="number" value={value} step={step} min={min} max={max} onChange={e => onChange(Number(e.target.value))} className="font-mono" />
    </Field>
  )
}
