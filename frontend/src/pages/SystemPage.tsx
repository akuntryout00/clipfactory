import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Save, X } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { CaptionOverrides } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { CaptionSettingsForm } from "@/components/CaptionSettingsForm"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function SystemPage() {
  const { data: s, error } = useQuery({ queryKey: ["system"], queryFn: api.system, refetchInterval: 15000 })
  const ok = (v: boolean) => v ? <Check className="inline size-4 text-ready" /> : <X className="inline size-4 text-fail" />
  return (
    <div>
      <PageHeader eyebrow="Health" title="System">
        <p className="mt-1 text-sm text-muted-foreground">Providers, keys, ffmpeg and storage as the API sees them.</p>
      </PageHeader>
      <div className="grid gap-4 px-8 py-6 md:grid-cols-2 xl:grid-cols-3">
        {error && <p className="text-fail">API unreachable: {String(error)}</p>}
        {s && (<>
          <Card><CardHeader><CardTitle className="text-sm">LLM</CardTitle></CardHeader><CardContent className="space-y-1 font-mono text-xs">
            <div>provider <b>{s.llm_provider}</b></div><div>model {s.openai_model}</div><div>OPENAI_API_KEY {ok(s.openai_key_set)}</div></CardContent></Card>
          <Card><CardHeader><CardTitle className="text-sm">Voice</CardTitle></CardHeader><CardContent className="space-y-1 font-mono text-xs">
            <div>provider <b>{s.voice_provider}</b></div><div>ELEVENLABS_API_KEY {ok(s.elevenlabs_key_set)}</div><div>ELEVENLABS_VOICE_ID {ok(s.elevenlabs_voice_id_set)}</div></CardContent></Card>
          <Card><CardHeader><CardTitle className="text-sm">Render</CardTitle></CardHeader><CardContent className="space-y-1 font-mono text-xs">
            <div>{s.ffmpeg}</div><div>captions (libass) {ok(s.render_ok)}</div>{s.render_missing.map(m => <div key={m} className="text-fail">{m}</div>)}</CardContent></Card>
          <Card><CardHeader><CardTitle className="text-sm">Library</CardTitle></CardHeader><CardContent className="space-y-1 font-mono text-xs">
            <div>assets {s.assets_count} ({s.assets_approved} approved)</div><div>projects {s.projects_count}</div><div>music {s.music_tracks.length ? s.music_tracks.join(", ") : "none (voice only)"}</div></CardContent></Card>
          {s.lab && <Card><CardHeader><CardTitle className="text-sm">AI Lab (separate module)</CardTitle></CardHeader><CardContent className="space-y-1 font-mono text-xs">
            <div>images {s.lab.image_provider} · {s.lab.image_model} · {s.lab.image_size}</div>
            <div>video {s.lab.video_provider} · {s.lab.video_model}</div>
            <div>planner {s.lab.planner}</div>
            <div>GOOGLE_API_KEY {ok(s.lab.google_key_set)}</div></CardContent></Card>}
          <Card><CardHeader><CardTitle className="text-sm">Paths</CardTitle></CardHeader><CardContent className="space-y-1 break-all font-mono text-xs">
            <div>assets {s.assets_dir}</div><div>storage {s.storage_dir}</div><div>fonts {s.fonts_dir}</div><div>db {s.database_url}</div><div>persona {s.default_persona}</div></CardContent></Card>
        </>)}
      </div>
      <CaptionSettingsCard />
    </div>
  )
}

/** Global caption font / position settings — the default for every new render; projects can override them. */
function CaptionSettingsCard() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ["caption-settings"], queryFn: api.captionSettings })
  const [ov, setOv] = useState<CaptionOverrides>({})
  const [dirty, setDirty] = useState(false)
  useEffect(() => { if (data && !dirty) setOv(data.overrides) }, [data, dirty])
  const save = useMutation({
    mutationFn: () => api.saveCaptionSettings(ov),
    onSuccess: () => { toast.success("Caption settings saved — applied on the next render of every project"); setDirty(false); qc.invalidateQueries({ queryKey: ["caption-settings"] }); qc.invalidateQueries({ queryKey: ["project"] }) },
    onError: e => toast.error(e.message),
  })
  return (
    <div className="px-8 pb-10">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-sm">
            <span>Captions — font &amp; position <span className="ml-2 font-mono text-[11px] font-normal text-muted-foreground">applies to all projects · a project can override</span></span>
            <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}><Save className="size-3.5" /> {save.isPending ? "Saving…" : "Save"}</Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data ? <CaptionSettingsForm base={data.defaults} value={ov} onChange={v => { setOv(v); setDirty(true) }} scopeLabel="template default" /> : <p className="text-sm text-muted-foreground">Loading…</p>}
        </CardContent>
      </Card>
    </div>
  )
}
