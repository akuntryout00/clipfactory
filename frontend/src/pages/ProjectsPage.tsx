import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { api, fmtDate } from "@/lib/api"
import { personaLabel, usePersona } from "@/lib/persona"
import type { Project } from "@/lib/types"
import { PageHeader } from "@/components/PageHeader"
import { StatusBadge } from "@/components/StatusBadge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const RUNNING = new Set(["GENERATING_SCRIPT", "GENERATING_VOICE", "PLANNING", "SELECTING_ASSETS", "GENERATING_CAPTIONS", "RENDERING"])

export default function ProjectsPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [status, setStatus] = useState("ALL")
  const [tpl, setTpl] = useState("ALL")
  const { activeId, active } = usePersona()
  const { data, isLoading } = useQuery({
    queryKey: ["projects", activeId], queryFn: () => api.projects(activeId || undefined), enabled: !!activeId,
    refetchInterval: q => (q.state.data?.some(p => RUNNING.has(p.status)) ? 3000 : 15000),
  })
  const del = useMutation({
    mutationFn: api.deleteProject,
    onSuccess: () => { toast.success("Project deleted"); qc.invalidateQueries({ queryKey: ["projects"] }) },
    onError: e => toast.error(e.message),
  })
  const rows = useMemo(() => (data ?? []).filter(p => (status === "ALL" || p.status === status) && (tpl === "ALL" || p.template_id === tpl)), [data, status, tpl])
  const templates = useMemo(() => Array.from(new Set((data ?? []).map(p => p.template_id))).sort(), [data])
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const p of data ?? []) c[p.status] = (c[p.status] ?? 0) + 1
    return c
  }, [data])

  return (
    <div>
      <PageHeader eyebrow="Production line" title="Projects"
        actions={<Button onClick={() => nav("/generate")}><Plus className="size-4" /> New video</Button>}>
        <p className="mt-1 text-sm text-muted-foreground">
          <span className="text-foreground">{personaLabel(active)}</span> · {data?.length ?? 0} projects · {counts.READY ?? 0} ready · {counts.APPROVED ?? 0} approved · {counts.FAILED ?? 0} failed
        </p>
      </PageHeader>
      <div className="flex items-center gap-2 px-8 py-4">
        <select value={status} onChange={e => setStatus(e.target.value)} className="h-8 rounded-md border border-input bg-card px-2 text-sm">
          <option value="ALL">All statuses</option>
          {["DRAFT", "READY", "APPROVED", "FAILED", "RENDERING", "GENERATING_SCRIPT", "GENERATING_VOICE", "PLANNING"].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={tpl} onChange={e => setTpl(e.target.value)} className="h-8 rounded-md border border-input bg-card px-2 text-sm">
          <option value="ALL">All templates</option>
          {templates.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <div className="px-8 pb-10">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[150px]">Status</TableHead>
              <TableHead>Topic</TableHead>
              <TableHead className="w-[160px]">Template</TableHead>
              <TableHead className="w-[90px] text-right">Length</TableHead>
              <TableHead className="w-[130px]">Versions</TableHead>
              <TableHead className="w-[170px]">Created</TableHead>
              <TableHead className="w-[60px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && <TableRow><TableCell colSpan={7} className="text-muted-foreground">Loading…</TableCell></TableRow>}
            {!isLoading && rows.length === 0 && (
              <TableRow><TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                No projects yet. <Link className="text-primary underline" to="/generate">Generate your first video</Link>.
              </TableCell></TableRow>
            )}
            {rows.map((p: Project) => (
              <TableRow key={p.id} className="cursor-pointer" onClick={() => nav(`/projects/${p.id}`)}>
                <TableCell><StatusBadge status={p.status} /></TableCell>
                <TableCell>
                  <div className="font-medium">{p.topic}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{p.id}{p.stage_message && RUNNING.has(p.status) ? ` · ${p.stage_message}` : ""}</div>
                </TableCell>
                <TableCell className="font-mono text-xs">{p.template_id}</TableCell>
                <TableCell className="text-right font-mono text-xs">{p.actual_duration ? `${p.actual_duration.toFixed(1)}s` : `${p.target_duration}s*`}</TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">s{p.script_version} · v{p.voice_version} · p{p.plan_version} · r{p.render_version}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{fmtDate(p.created_at)}</TableCell>
                <TableCell onClick={e => e.stopPropagation()}>
                  <Button variant="ghost" size="icon-sm" aria-label="Delete project" disabled={RUNNING.has(p.status)}
                    onClick={() => { if (confirm(`Delete project ${p.id}? This removes its renders too.`)) del.mutate(p.id) }}>
                    <Trash2 className="size-4 text-muted-foreground" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
