import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRight, Check, Clapperboard, KeyRound, PlugZap, X } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { ProviderSettings, ProviderTestResult } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { cn } from "@/lib/utils"

type Form = Record<string, string>
const EMPTY: Form = {}

/**
 * First-run setup / provider settings. Keys are stored in the app database and override .env.
 * Required for videos: OpenAI (scripts, planning) + ElevenLabs (voice). Google / fal.ai only power the AI Lab.
 */
export default function SetupPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ["provider-settings"], queryFn: api.providerSettings })
  const [form, setForm] = useState<Form>(EMPTY)
  const [tests, setTests] = useState<Record<string, ProviderTestResult | "running" | undefined>>({})
  const [offline, setOffline] = useState(false)
  useEffect(() => { if (data) setOffline(data.llm_provider === "fake" && data.voice_provider === "fake") }, [data])
  const firstRun = !!data?.setup_required
  const f = (k: string) => form[k] ?? ""
  const set = (k: string, v: string) => setForm(x => ({ ...x, [k]: v }))
  const placeholder = (k: string) => data?.fields[k]?.value ?? ""
  const isSet = (k: string) => !!data?.fields[k]?.set
  const valuesFor = (keys: string[]) => Object.fromEntries(keys.filter(k => form[k] !== undefined).map(k => [k, form[k]]))

  const runTest = async (provider: string, keys: string[]) => {
    setTests(t => ({ ...t, [provider]: "running" }))
    try {
      const r = await api.testProvider(provider, valuesFor(keys))
      setTests(t => ({ ...t, [provider]: r }))
      if (r.ok && provider === "elevenlabs" && r.voices?.length && !f("elevenlabs_voice_id") && !isSet("elevenlabs_voice_id")) set("elevenlabs_voice_id", r.voices[0].id)
    } catch (e) { setTests(t => ({ ...t, [provider]: { ok: false, message: (e as Error).message } })) }
  }
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, string | null> = { ...form }
      body.llm_provider = offline ? "fake" : "openai"
      body.voice_provider = offline ? "fake" : "elevenlabs"
      return api.saveProviderSettings(body)
    },
    onSuccess: (d: ProviderSettings) => {
      setForm(EMPTY); qc.invalidateQueries({ queryKey: ["provider-settings"] }); qc.invalidateQueries({ queryKey: ["system"] })
      if (d.setup_required) toast.warning(`Saved — still missing: ${d.missing.join(", ")}`)
      else { toast.success(firstRun ? "You're set up — next: create your first persona" : "Settings saved"); if (firstRun) nav("/personas") }
    },
    onError: e => toast.error(e.message),
  })
  const ev = tests.elevenlabs
  const voices = ev && ev !== "running" && ev.ok ? ev.voices ?? [] : []

  return (
    <div className="mx-auto max-w-3xl px-8 py-10">
      <div className="mb-8 flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-md bg-primary text-primary-foreground"><Clapperboard className="size-5" /></span>
        <div>
          <h1 className="font-heading text-2xl font-bold">{firstRun ? "Welcome to ClipFactory" : "Provider settings"}</h1>
          <p className="text-sm text-muted-foreground">{firstRun ? "Connect the AI providers once; everything else happens in the app. Keys are stored only in your local database." : "Keys and models used by the pipeline. Saved values override .env."}</p>
        </div>
      </div>

      {isLoading ? <p className="text-muted-foreground">Loading…</p> : (
        <div className="space-y-8">
          <Section title="Required for videos" hint="script + scene planning, and the voice-over">
            <ProviderBlock name="OpenAI" status={tests.openai} onTest={() => runTest("openai", ["openai_api_key", "openai_model"])} testable={!offline}>
              <KeyInput id="openai_api_key" label="OpenAI API key" value={f("openai_api_key")} onChange={v => set("openai_api_key", v)} isSet={isSet("openai_api_key")} placeholder={placeholder("openai_api_key")} hint="platform.openai.com → API keys. Used for scripts, scene plans, B-roll tagging, personas, topics." />
              <Field id="openai_model" label="Model" value={f("openai_model")} onChange={v => set("openai_model", v)} placeholder={placeholder("openai_model") || "gpt-4.1"} mono />
            </ProviderBlock>
            <ProviderBlock name="ElevenLabs" status={tests.elevenlabs} onTest={() => runTest("elevenlabs", ["elevenlabs_api_key"])} testable={!offline}>
              <KeyInput id="elevenlabs_api_key" label="ElevenLabs API key" value={f("elevenlabs_api_key")} onChange={v => set("elevenlabs_api_key", v)} isSet={isSet("elevenlabs_api_key")} placeholder={placeholder("elevenlabs_api_key")} hint="elevenlabs.io → Profile → API keys. Test the connection to pick a voice from your account." />
              <div>
                <Label htmlFor="voice" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Default voice</Label>
                {voices.length > 0 ? (
                  <select id="voice" value={f("elevenlabs_voice_id") || placeholder("elevenlabs_voice_id")} onChange={e => set("elevenlabs_voice_id", e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
                    {placeholder("elevenlabs_voice_id") && !voices.some(v => v.id === placeholder("elevenlabs_voice_id")) && <option value={placeholder("elevenlabs_voice_id")}>current · {placeholder("elevenlabs_voice_id")}</option>}
                    {voices.map(v => <option key={v.id} value={v.id}>{v.name}{v.labels?.accent ? ` · ${v.labels.accent}` : ""}{v.labels?.gender ? ` · ${v.labels.gender}` : ""}</option>)}
                  </select>
                ) : <Input id="voice" value={f("elevenlabs_voice_id")} onChange={e => set("elevenlabs_voice_id", e.target.value)} placeholder={placeholder("elevenlabs_voice_id") || "voice id — or test the key above to choose from a list"} className="font-mono" />}
                <p className="mt-1 text-[11px] text-muted-foreground">Each persona can override the voice later.</p>
              </div>
            </ProviderBlock>
            <label className="flex items-start gap-2 rounded-md border border-dashed border-border p-3 text-sm">
              <input type="checkbox" className="scrub mt-0.5 size-4" checked={offline} onChange={e => setOffline(e.target.checked)} />
              <span><b>Offline dry run</b> — use the built-in fake providers (placeholder script, beep voice) to try the pipeline without any key. Switch back here any time.</span>
            </label>
          </Section>

          <Section title="Optional · AI Lab" hint="fully generated clips — keyframes + video models; skip if you only use your own B-roll">
            <ProviderBlock name="Google AI (Gemini Omni / Veo)" status={tests.google} onTest={() => runTest("google", ["google_api_key"])}>
              <KeyInput id="google_api_key" label="Google AI API key" value={f("google_api_key")} onChange={v => set("google_api_key", v)} isSet={isSet("google_api_key")} placeholder={placeholder("google_api_key")} hint="aistudio.google.com → Get API key" />
            </ProviderBlock>
            <ProviderBlock name="fal.ai (Seedance, MiniMax, Kling)" status={tests.fal} onTest={() => runTest("fal", ["fal_key"])}>
              <KeyInput id="fal_key" label="fal.ai key" value={f("fal_key")} onChange={v => set("fal_key", v)} isSet={isSet("fal_key")} placeholder={placeholder("fal_key")} hint="fal.ai → Dashboard → Keys" />
            </ProviderBlock>
          </Section>

          <div className="flex items-center justify-between border-t border-border pt-5">
            <p className="text-xs text-muted-foreground">Keys are saved to the app database (Postgres volume) and never sent anywhere except the provider itself. To rotate a key, paste a new one; to remove it, clear the field and save.</p>
            <Button size="lg" disabled={save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving…" : firstRun ? <>Save & continue <ArrowRight className="size-4" /></> : "Save settings"}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function Section({ title, hint, children }: { title: string; hint: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <div><h2 className="font-mono text-[10px] uppercase tracking-[0.18em] text-primary">{title}</h2><p className="text-xs text-muted-foreground">{hint}</p></div>
      {children}
    </section>
  )
}

function ProviderBlock({ name, status, onTest, testable = true, children }: { name: string; status: ProviderTestResult | "running" | undefined; onTest: () => void; testable?: boolean; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-heading font-semibold"><KeyRound className="size-4 text-muted-foreground" /> {name}</span>
        <span className="flex items-center gap-2">
          {status && status !== "running" && <span className={cn("flex items-center gap-1 text-xs", status.ok ? "text-ready" : "text-fail")}>{status.ok ? <Check className="size-3.5" /> : <X className="size-3.5" />} {status.message}</span>}
          {testable && <Button size="sm" variant="outline" onClick={onTest} disabled={status === "running"}><PlugZap className="size-3.5" /> {status === "running" ? "Testing…" : "Test connection"}</Button>}
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </div>
  )
}

function KeyInput({ id, label, value, onChange, isSet, placeholder, hint }: { id: string; label: string; value: string; onChange: (v: string) => void; isSet: boolean; placeholder: string; hint: string }) {
  return (
    <div className="sm:col-span-2">
      <Label htmlFor={id} className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">{label} {isSet && <span className="ml-1 rounded bg-ready/15 px-1.5 py-0.5 font-mono text-[10px] normal-case tracking-normal text-ready">set</span>}</Label>
      <Input id={id} type="password" autoComplete="off" value={value} onChange={e => onChange(e.target.value)} placeholder={isSet ? `${placeholder} — paste a new key to replace` : "paste your key"} className="font-mono" />
      <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
    </div>
  )
}

function Field({ id, label, value, onChange, placeholder, mono }: { id: string; label: string; value: string; onChange: (v: string) => void; placeholder: string; mono?: boolean }) {
  return (
    <div>
      <Label htmlFor={id} className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">{label}</Label>
      <Input id={id} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} className={mono ? "font-mono" : undefined} />
    </div>
  )
}
