import { useEffect, useMemo, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, Sparkles } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { Persona } from "@/lib/types"
import { PersonaForm } from "@/components/PersonaEditor"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

/** country → default language of the videos (the user can still override) */
const COUNTRIES: { code: string; name: string; lang: string }[] = [
  { code: "US", name: "United States", lang: "en-US" }, { code: "GB", name: "United Kingdom", lang: "en-GB" },
  { code: "CA", name: "Canada", lang: "en-US" }, { code: "AU", name: "Australia", lang: "en-AU" },
  { code: "IE", name: "Ireland", lang: "en-GB" }, { code: "DE", name: "Germany", lang: "de-DE" },
  { code: "AT", name: "Austria", lang: "de-DE" }, { code: "CH", name: "Switzerland", lang: "de-DE" },
  { code: "FR", name: "France", lang: "fr-FR" }, { code: "ES", name: "Spain", lang: "es-ES" },
  { code: "MX", name: "Mexico", lang: "es-MX" }, { code: "IT", name: "Italy", lang: "it-IT" },
  { code: "PT", name: "Portugal", lang: "pt-PT" }, { code: "BR", name: "Brazil", lang: "pt-BR" },
  { code: "NL", name: "Netherlands", lang: "nl-NL" }, { code: "SE", name: "Sweden", lang: "sv-SE" },
  { code: "PL", name: "Poland", lang: "pl-PL" }, { code: "TR", name: "Türkiye", lang: "tr-TR" },
  { code: "AZ", name: "Azerbaijan", lang: "az-AZ" }, { code: "RU", name: "Russia", lang: "ru-RU" },
  { code: "UA", name: "Ukraine", lang: "uk-UA" }, { code: "IN", name: "India", lang: "en-IN" },
  { code: "AE", name: "United Arab Emirates", lang: "en-US" }, { code: "JP", name: "Japan", lang: "ja-JP" },
  { code: "KR", name: "South Korea", lang: "ko-KR" }, { code: "SG", name: "Singapore", lang: "en-US" },
  { code: "ZA", name: "South Africa", lang: "en-GB" }, { code: "NZ", name: "New Zealand", lang: "en-AU" },
  { code: "OTHER", name: "Other", lang: "en-US" },
]
const LANGUAGES = ["en-US", "en-GB", "en-AU", "en-IN", "de-DE", "fr-FR", "es-ES", "es-MX", "it-IT", "pt-PT", "pt-BR", "nl-NL", "sv-SE", "pl-PL", "tr-TR", "az-AZ", "ru-RU", "uk-UA", "ja-JP", "ko-KR"]

const STEPS = ["Name", "Where & age", "About", "Review"] as const

/** 3 questions → AI drafts the rest → user reviews and creates. Display name and id are set by the system. */
export function PersonaWizard({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: (p: Persona) => void }) {
  const [step, setStep] = useState(0)
  const [name, setName] = useState("")
  const [country, setCountry] = useState("US")
  const [city, setCity] = useState("")
  const [age, setAge] = useState<string>("")
  const [language, setLanguage] = useState("en-US")
  const [langTouched, setLangTouched] = useState(false)
  const [about, setAbout] = useState("")
  const [draft, setDraft] = useState<Persona | null>(null)

  useEffect(() => { if (open) { setStep(0); setName(""); setCountry("US"); setCity(""); setAge(""); setLanguage("en-US"); setLangTouched(false); setAbout(""); setDraft(null) } }, [open])
  useEffect(() => { if (!langTouched) setLanguage(COUNTRIES.find(c => c.code === country)?.lang ?? "en-US") }, [country, langTouched])

  const location = useMemo(() => {
    const c = COUNTRIES.find(x => x.code === country)
    const cn = c && c.code !== "OTHER" ? c.name : ""
    return [city.trim(), cn].filter(Boolean).join(", ")
  }, [city, country])

  const gen = useMutation({
    mutationFn: () => api.draftPersona({ name: name.trim(), age: age ? Number(age) : null, location: location || null, language, about: about.trim() }),
    onSuccess: d => { setDraft(d); setStep(3) },
    onError: e => toast.error(e.message),
  })

  const nameOk = name.trim().length >= 2
  const aboutOk = about.trim().length >= 10
  const next = () => {
    if (step === 2) { gen.mutate(); return }
    setStep(s => Math.min(s + 1, 3))
  }
  const back = () => setStep(s => Math.max(s - 1, 0))
  const onKeyNext = (e: React.KeyboardEvent) => { if (e.key === "Enter" && !e.shiftKey && step < 2) { e.preventDefault(); if (canNext) next() } }
  const canNext = step === 0 ? nameOk : step === 1 ? true : step === 2 ? aboutOk && !gen.isPending : false

  return (
    <Dialog open={open} onOpenChange={o => { if (!o && !gen.isPending) onClose() }}>
      <DialogContent className={cn("max-h-[90vh] overflow-y-auto", step === 3 ? "sm:max-w-4xl" : "sm:max-w-lg")}>
        <DialogHeader>
          <DialogTitle className="font-heading">New persona</DialogTitle>
          <DialogDescription>{step < 3 ? "Three short questions — AI fills in the rest, you review before anything is saved." : "Review what AI drafted. Everything is editable; nothing is saved until you confirm."}</DialogDescription>
        </DialogHeader>

        <ol className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em]">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-2">
              <span className={cn("grid size-5 place-items-center rounded-full border text-[10px]", i < step ? "border-primary bg-primary text-primary-foreground" : i === step ? "border-primary text-primary" : "border-border text-muted-foreground")}>{i + 1}</span>
              <span className={i === step ? "text-foreground" : "text-muted-foreground"}>{s}</span>
              {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-border" />}
            </li>
          ))}
        </ol>

        {step === 0 && (
          <div className="space-y-2 py-2">
            <Label htmlFor="pw-name" className="font-heading text-lg">What is the persona's name?</Label>
            <Input id="pw-name" autoFocus value={name} onChange={e => setName(e.target.value)} onKeyDown={onKeyNext} placeholder="e.g. Anna" className="h-11 text-base" />
            <p className="text-xs text-muted-foreground">The first name the voice uses for itself. The list name and the technical id are generated from it.</p>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4 py-2">
            <div>
              <Label className="font-heading text-lg">Where do they live, and how old are they?</Label>
              <p className="text-xs text-muted-foreground">Shapes vocabulary, references and the default language of the videos.</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr]">
              <div>
                <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Country</Label>
                <select value={country} onChange={e => setCountry(e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
                  {COUNTRIES.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">City <span className="normal-case tracking-normal">(optional)</span></Label>
                <Input value={city} onChange={e => setCity(e.target.value)} onKeyDown={onKeyNext} placeholder="Berlin" />
              </div>
              <div>
                <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Age</Label>
                <Input type="number" min={5} max={120} value={age} onChange={e => setAge(e.target.value)} onKeyDown={onKeyNext} placeholder="29" />
              </div>
              <div>
                <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Language of the videos</Label>
                <select value={language} onChange={e => { setLangTouched(true); setLanguage(e.target.value) }} className="h-9 w-full rounded-md border border-input bg-card px-2 font-mono text-sm">
                  {LANGUAGES.map(l => <option key={l} value={l}>{l}</option>)}
                </select>
                <p className="mt-1 text-[11px] text-muted-foreground">{langTouched ? "chosen by you" : "set from the country — change if needed"}</p>
              </div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-2 py-2">
            <Label htmlFor="pw-about" className="font-heading text-lg">Tell us about {name.trim() || "them"}</Label>
            <Textarea id="pw-about" autoFocus rows={7} value={about} onChange={e => setAbout(e.target.value)}
              placeholder={"What do they do for a living, for how long? What did they do before? Hobbies, habits, what they care about, how they talk, who they want to reach…"} />
            <p className="text-xs text-muted-foreground">Free text, any language. AI turns this into background, audience, content pillars, tone, things to avoid and tools — you review everything next.</p>
          </div>
        )}

        {step === 3 && draft && (
          <PersonaForm initial={draft} mode="create" submitLabel="Create persona"
            onDone={p => {
              onCreated?.(p); onClose()
              // plan the B-roll to film for the new persona in the background (PRD: 100 clips per persona)
              api.generateShotlist(p.id, { target_count: 100, match_existing: false })
                .then(d => toast.success(`B-roll shot list for ${p.identity?.name ?? p.id} ready — ${d.items_total} shots, ${d.wanted} clips to film (see B-roll)`))
                .catch(e => toast.warning(`Shot list not generated: ${e.message}`))
            }} onCancel={() => setStep(2)} />
        )}

        {step < 3 && (
          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button type="button" variant="ghost" onClick={step === 0 ? onClose : back} disabled={gen.isPending}>
              {step === 0 ? "Cancel" : <><ArrowLeft className="size-4" /> Back</>}
            </Button>
            <Button type="button" onClick={next} disabled={!canNext}>
              {step === 2 ? (gen.isPending ? <><Sparkles className="size-4 animate-pulse" /> Drafting with AI…</> : <><Sparkles className="size-4" /> Draft with AI</>) : <>Next <ArrowRight className="size-4" /></>}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
