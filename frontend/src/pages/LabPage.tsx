import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FlaskConical, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { lab } from "@/lib/api"
import { fmtDate } from "@/lib/api"
import type { LabVideo } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const RUNNING = new Set(["GENERATING_IMAGES", "ANIMATING"])
const STATUS_STYLE: Record<string, string> = { DONE: "text-ready border-ready/30 bg-ready/10", FAILED: "text-fail border-fail/30 bg-fail/10", IMAGES_READY: "text-primary border-primary/40 bg-primary/10" }

export default function LabPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [prompt, setPrompt] = useState("")
  const [style, setStyle] = useState("")
  const [duration, setDuration] = useState(18)
  const { data } = useQuery({ queryKey: ["lab"], queryFn: lab.list, refetchInterval: q => (q.state.data?.some(v => RUNNING.has(v.status)) ? 4000 : 20000) })
  const create = useMutation({
    mutationFn: async () => {
      const v = await lab.create({ prompt: prompt.trim(), target_duration: duration, style: style.trim() || null })
      await lab.generateImages(v.id)
      return v
    },
    onSuccess: v => { toast.success("Storyboard planned — generating keyframe images"); nav(`/lab/${v.id}`) },
    onError: e => toast.error(e.message),
  })
  const del = useMutation({ mutationFn: lab.delete, onSuccess: () => { toast.success("Deleted"); qc.invalidateQueries({ queryKey: ["lab"] }) }, onError: e => toast.error(e.message) })
  const segs = Math.max(2, Math.ceil(duration / 8)), segLen = Math.max(4, Math.min(8, Math.round(duration / segs)))

  return (
    <div>
      <PageHeader eyebrow="Separate module · fully AI-generated" title="AI Lab">
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Describe a video. Step 1: OpenAI images paint the keyframes (start, in-betweens, end) in 9:16. Step 2: Google animates each pair of frames into a clip; clips are joined into one vertical MP4. Nothing here touches your B-roll library or templates.</p>
      </PageHeader>
      <div className="grid gap-8 px-8 py-6 xl:grid-cols-[1fr_1.1fr]">
        <form className="space-y-5" onSubmit={e => { e.preventDefault(); if (prompt.trim().length >= 5) create.mutate() }}>
          <div>
            <Label htmlFor="lp" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">What video do you want?</Label>
            <Textarea id="lp" rows={5} value={prompt} onChange={e => setPrompt(e.target.value)}
              placeholder="A solo founder's morning in a sunlit cafe: a steaming coffee, a laptop opening, typing, then stepping out into a bright city street. Warm cinematic light, calm and motivating." />
          </div>
          <div className="grid grid-cols-[1fr_200px] gap-4">
            <div>
              <Label htmlFor="ls" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Visual style (optional)</Label>
              <Input id="ls" value={style} onChange={e => setStyle(e.target.value)} placeholder="cinematic realistic · anime · claymation · film noir…" />
            </div>
            <div>
              <Label htmlFor="ld" className="mb-2 block text-xs uppercase tracking-wider text-muted-foreground">Length · <span className="font-mono text-foreground">{duration}s</span></Label>
              <input id="ld" type="range" min={15} max={25} step={1} value={duration} onChange={e => setDuration(Number(e.target.value))} className="scrub w-full" />
              <div className="font-mono text-[11px] text-muted-foreground">{segs + 1} keyframes · {segs} × {segLen}s clips</div>
            </div>
          </div>
          <Button type="submit" size="lg" disabled={prompt.trim().length < 5 || create.isPending}><FlaskConical className="size-4" /> {create.isPending ? "Planning…" : "Plan & generate keyframes"}</Button>
          <p className="text-xs text-muted-foreground">You'll review the keyframe images (and can regenerate any of them) before the video is animated.</p>
        </form>

        <section>
          <h2 className="mb-2 font-heading text-sm font-semibold">Your AI videos</h2>
          {!data?.length && <p className="text-sm text-muted-foreground">Nothing yet — your generated videos appear here.</p>}
          <ul className="divide-y divide-border rounded-md border border-border">
            {(data ?? []).map((v: LabVideo) => (
              <li key={v.id} className="flex cursor-pointer items-center gap-3 p-3 hover:bg-accent/40" onClick={() => nav(`/lab/${v.id}`)}>
                <div className="flex w-16 shrink-0 gap-0.5 overflow-hidden rounded">
                  {v.keyframes.filter(k => k.image_url).slice(0, 3).map(k => <img key={k.index} src={`/api${k.image_url}`} alt="" className="h-12 w-1/3 object-cover" />)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{v.prompt}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{v.id} · {v.target_duration}s · {v.n_segments}×{v.segment_seconds}s · {fmtDate(v.created_at)}</div>
                </div>
                <span className={cn("rounded border px-1.5 py-0.5 font-mono text-[10px]", STATUS_STYLE[v.status] ?? "text-muted-foreground border-border")}>{RUNNING.has(v.status) && <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-primary" />}{v.status.replace(/_/g, " ")}</span>
                <Button variant="ghost" size="icon-sm" aria-label="Delete" onClick={e => { e.stopPropagation(); if (confirm(`Delete ${v.id}?`)) del.mutate(v.id) }}><Trash2 className="size-4 text-muted-foreground" /></Button>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}
