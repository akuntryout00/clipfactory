import { useQuery } from "@tanstack/react-query"
import { Check, X } from "lucide-react"
import { api } from "@/lib/api"
import { PageHeader } from "@/components/PageHeader"
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
          <Card><CardHeader><CardTitle className="text-sm">Paths</CardTitle></CardHeader><CardContent className="space-y-1 break-all font-mono text-xs">
            <div>assets {s.assets_dir}</div><div>storage {s.storage_dir}</div><div>db {s.database_url}</div><div>persona {s.default_persona}</div></CardContent></Card>
        </>)}
      </div>
    </div>
  )
}
