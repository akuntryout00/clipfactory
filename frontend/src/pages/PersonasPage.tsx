import { useEffect, useState } from "react"
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Copy, Pencil, Plus, QrCode, RefreshCw, Send, Smartphone } from "lucide-react"
import { api, delivery, media } from "@/lib/api"
import type { InboxLink } from "@/lib/types"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
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
  const [inboxFor, setInboxFor] = useState<Persona | null>(null)
  const [tgFor, setTgFor] = useState<Persona | null>(null)
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
                  <span className="flex items-center gap-2"><PersonaAvatar id={p.id} />{personaLabel(p)}{isActive && <span className="rounded bg-primary/15 px-1.5 py-0.5 font-mono text-[10px] font-normal uppercase tracking-wider text-primary">active</span>}</span>
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-[11px] font-normal text-muted-foreground">{p.id}</span>
                    <Button size="sm" variant="outline" onClick={() => setTgFor(p)} title={p.telegram_bot_token_set ? `Telegram connected${p.telegram_chat_id ? ` · chat ${p.telegram_chat_id}` : " · no chat yet"}` : "Connect this persona's Telegram bot"}>
                      <Send className="size-3.5" /> {p.telegram_bot_token_set ? (p.telegram_chat_id ? "Telegram ✓" : "Telegram · pick chat") : "Add Telegram"}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setInboxFor(p)} title="Inbox link + QR for the phone that runs this account"><Smartphone className="size-3.5" /> Inbox</Button>
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
      <InboxLinkDialog persona={inboxFor} onClose={() => setInboxFor(null)} />
      <TelegramDialog persona={tgFor} onClose={() => setTgFor(null)} />
      <PersonaWizard open={creating} onClose={() => setCreating(false)} onCreated={p => setActiveId(p.id)} />
    </div>
  )
}

function Row({ label, items }: { label: string; items: string[] }) {
  if (!items?.length) return null
  return <div className="flex flex-wrap items-baseline gap-1"><span className="mr-1 font-mono text-[11px] text-primary">{label}</span>{items.map(i => <span key={i} className="rounded bg-secondary px-1.5 py-0.5 text-[11px]">{i}</span>)}</div>
}

/** Reference photo if one was uploaded on the AI B-roll page; hidden otherwise. */
function PersonaAvatar({ id }: { id: string }) {
  const [ok, setOk] = useState(true)
  if (!ok) return null
  return <img src={media.personaImage(id)} alt="" onError={() => setOk(false)} className="size-7 rounded-full border border-border object-cover" />
}

/** Token link + QR for the phone that runs this persona's TikTok account. */
function InboxLinkDialog({ persona, onClose }: { persona: Persona | null; onClose: () => void }) {
  const { data: settings } = useQuery({ queryKey: ["provider-settings"], queryFn: api.providerSettings, enabled: !!persona })
  const guess = typeof window !== "undefined" && !/localhost|127\.0\.0\.1/.test(window.location.host) ? window.location.origin : ""
  const [base, setBase] = useState("")
  const [link, setLink] = useState<InboxLink | null>(null)
  const effectiveBase = base || settings?.fields?.public_base_url?.value || guess
  useEffect(() => { setBase(""); setLink(null) }, [persona])
  useEffect(() => { if (persona && effectiveBase) delivery.inboxLink(persona.id, effectiveBase).then(setLink).catch(e => toast.error(e.message)) }, [persona, effectiveBase])
  const rotate = async () => { if (!persona) return; try { setLink(await delivery.rotateInboxLink(persona.id, effectiveBase)); toast.success("New link — the old one stopped working") } catch (e) { toast.error((e as Error).message) } }
  const copy = async () => { if (link) { await navigator.clipboard.writeText(link.url); toast.success("Link copied") } }
  return (
    <Dialog open={!!persona} onOpenChange={o => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading">Inbox for {persona ? personaLabel(persona) : ""}</DialogTitle>
          <DialogDescription>Open this link on the phone that runs the TikTok account (scan the QR). It lists the approved videos and slideshows for saving to Photos — no login; anyone with the link can see them, rotate it if it leaks.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Address phones can reach</Label>
            <Input value={base} onChange={e => setBase(e.target.value)} placeholder={settings?.fields?.public_base_url?.value || guess || "http://<this machine's LAN IP>:3000"} className="font-mono" />
            <p className="mt-1 text-[11px] text-muted-foreground">Same Wi-Fi: this machine's LAN IP (System Settings → Wi-Fi → Details). Elsewhere: a Tailscale name. Set it once in Settings to skip this field.</p>
          </div>
          {!effectiveBase && <p className="text-xs text-fail">Enter the address first — localhost only works on this computer.</p>}
          {link && (
            <div className="flex gap-4">
              <img src={delivery.qrUrl(link.persona_id, effectiveBase)} alt="QR code" className="size-44 rounded-md border border-border bg-white p-1" />
              <div className="min-w-0 flex-1 space-y-2">
                <div className="break-all rounded-md border border-border bg-surface-2 p-2 font-mono text-[11px]">{link.url}</div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={copy}><Copy className="size-3.5" /> Copy link</Button>
                  <Button size="sm" variant="ghost" onClick={rotate}><RefreshCw className="size-3.5" /> New link</Button>
                </div>
                <p className="text-[11px] text-muted-foreground"><QrCode className="mr-1 inline size-3" /> On the phone: open, then Share → Add to Home Screen for one-tap access.</p>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Add this persona's own Telegram bot: paste the token → connection is tested and saved → pick the chat the phone uses. */
function TelegramDialog({ persona, onClose }: { persona: Persona | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [token, setToken] = useState("")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [chats, setChats] = useState<{ id: string; title: string; type: string | null }[] | null>(null)
  const [manual, setManual] = useState("")
  const connected = !!persona?.telegram_bot_token_set
  useEffect(() => { setToken(""); setMsg(null); setChats(null); setManual("") }, [persona])
  const invalidate = () => qc.invalidateQueries({ queryKey: ["personas"] })
  const connect = async () => {
    if (!persona) return
    setBusy(true); setMsg(null)
    try { const r = await delivery.connectTelegram(persona.id, token.trim()); setMsg({ ok: true, text: `Connected: ${r.message}` }); setToken(""); invalidate() }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }) }
    finally { setBusy(false) }
  }
  const detect = async () => {
    if (!persona) return
    setBusy(true)
    try { const r = await delivery.telegramChats(persona.id); setChats(r.chats); if (!r.chats.length) setMsg({ ok: false, text: "No chats yet — from the phone, open the bot and send it any message (or add it to a group and write there), then detect again." }) }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }) }
    finally { setBusy(false) }
  }
  const pick = async (id: string) => {
    if (!persona) return
    setBusy(true)
    try { const r = await delivery.setTelegramChat(persona.id, id); setMsg({ ok: r.ok, text: r.ok ? `Chat saved — ${r.message}` : r.message }); invalidate() }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }) }
    finally { setBusy(false) }
  }
  return (
    <Dialog open={!!persona} onOpenChange={o => { if (!o && !busy) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading">Telegram for {persona ? personaLabel(persona) : ""}</DialogTitle>
          <DialogDescription>One bot per persona/phone. Create it in Telegram with @BotFather (/newbot), paste the token here — the connection is tested and saved. Then pick the chat the phone uses; approved videos are sent there automatically.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label htmlFor="tg-token" className="mb-1 block text-xs uppercase tracking-wider text-muted-foreground">Bot token {connected && <span className="ml-1 rounded bg-ready/15 px-1.5 py-0.5 font-mono text-[10px] normal-case tracking-normal text-ready">connected {persona?.telegram_bot_token_hint}</span>}</Label>
            <div className="flex gap-2">
              <Input id="tg-token" type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} placeholder={connected ? "paste a new token to replace" : "123456789:AAH…"} className="font-mono" onKeyDown={e => { if (e.key === "Enter" && token.trim()) connect() }} />
              <Button onClick={connect} disabled={busy || token.trim().length < 10}><Send className="size-4" /> {busy ? "…" : connected ? "Replace" : "Add"}</Button>
            </div>
          </div>
          {connected && (
            <div className="rounded-md border border-border bg-card p-3">
              <div className="mb-1 flex items-center justify-between"><span className="font-heading text-sm font-semibold">Chat for this phone</span>{persona?.telegram_chat_id && <span className="font-mono text-[11px] text-ready">current: {persona.telegram_chat_id}</span>}</div>
              <p className="text-xs text-muted-foreground">On the phone: open the bot and send it any message (or add it to a group/channel and post there). Then detect — pick the chat and a hello message is sent.</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={detect} disabled={busy}><RefreshCw className="size-3.5" /> Detect chats</Button>
                <Input value={manual} onChange={e => setManual(e.target.value)} placeholder="or type a chat id" className="h-8 w-44 font-mono" />
                <Button size="sm" variant="ghost" disabled={busy || !manual.trim()} onClick={() => pick(manual.trim())}>Use</Button>
              </div>
              {chats && chats.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {chats.map(c => <li key={c.id}><button type="button" onClick={() => pick(c.id)} className={cn("flex w-full items-center justify-between rounded-md border px-2 py-1.5 text-left text-sm hover:border-primary", persona?.telegram_chat_id === c.id ? "border-primary bg-primary/5" : "border-border")}><span>{c.title} <span className="font-mono text-[11px] text-muted-foreground">{c.type}</span></span><span className="font-mono text-[11px] text-muted-foreground">{c.id}</span></button></li>)}
                </ul>
              )}
            </div>
          )}
          {msg && <p className={cn("text-sm", msg.ok ? "text-ready" : "text-fail")}>{msg.text}</p>}
        </div>
      </DialogContent>
    </Dialog>
  )
}
