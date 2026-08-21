import type { Artifacts, Asset, Candidate, ClipAnalysis, LabVideo, Persona, Plan, Project, SystemInfo, Template } from "./types"

export const API = import.meta.env.VITE_API_BASE || "/api"

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, { headers: { "content-type": "application/json", ...(init?.headers || {}) }, ...init })
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  system: () => req<SystemInfo>("/system"),
  templates: () => req<Template[]>("/templates"),
  captionStyles: () => req<string[]>("/caption-styles"),
  createTemplate: (t: Template) => req<Template>("/templates", { method: "POST", body: JSON.stringify(t) }),
  updateTemplate: (t: Template) => req<Template>(`/templates/${t.id}`, { method: "PUT", body: JSON.stringify(t) }),
  deleteTemplate: (id: string) => req<void>(`/templates/${id}`, { method: "DELETE" }),
  personas: () => req<Persona[]>("/personas"),
  projects: () => req<Project[]>("/projects"),
  project: (id: string) => req<Project>(`/projects/${id}`),
  createProject: (body: { topic: string; template_id: string; target_duration?: number; persona_id?: string }) =>
    req<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
  deleteProject: (id: string) => req<void>(`/projects/${id}`, { method: "DELETE" }),
  action: (id: string, action: "generate" | "regenerate-script" | "change-assets" | "render" | "retry") =>
    req<{ project_id: string; action: string }>(`/projects/${id}/${action}`, { method: "POST" }),
  approve: (id: string) => req<Project>(`/projects/${id}/approve`, { method: "POST" }),
  plan: (id: string) => req<Plan>(`/projects/${id}/plan`),
  artifacts: (id: string) => req<Artifacts>(`/projects/${id}/artifacts`),
  suggestions: (id: string, order: number) => req<Candidate[]>(`/projects/${id}/scenes/${order}/suggestions`),
  setSceneAsset: (id: string, order: number, asset_id: string) =>
    req<unknown>(`/projects/${id}/scenes/${order}/asset`, { method: "POST", body: JSON.stringify({ asset_id }) }),
  assets: () => req<Asset[]>("/assets"),
  searchAssets: (q: string) => req<Candidate[]>(`/assets/search?q=${encodeURIComponent(q)}&limit=30`),
  patchAsset: (id: string, patch: Partial<Asset>) => req<Asset>(`/assets/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  analyzeAsset: async (file: File) => {
    const fd = new FormData(); fd.append("file", file)
    const res = await fetch(`${API}/assets/analyze`, { method: "POST", body: fd })
    if (!res.ok) { let d = res.statusText; try { d = (await res.json()).detail ?? d } catch { /* ignore */ } throw new Error(typeof d === "string" ? d : JSON.stringify(d)) }
    return res.json() as Promise<ClipAnalysis>
  },
  deleteAsset: (id: string, keepFile = false) => req<void>(`/assets/${id}${keepFile ? "?keep_file=true" : ""}`, { method: "DELETE" }),
  importAssets: () => req<{ created: number; updated: number; errors: string[] }>("/assets/import", { method: "POST" }),
  enrichAssets: () => req<{ enriched: number }>("/assets/enrich", { method: "POST" }),
  uploadAsset: (form: FormData, onProgress?: (pct: number) => void) =>
    new Promise<Asset & { enriched?: boolean; enrichError?: string }>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open("POST", `${API}/assets/upload`)
      xhr.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100)) }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve({ ...JSON.parse(xhr.responseText), enriched: xhr.getResponseHeader("X-Enriched") === "true", enrichError: xhr.getResponseHeader("X-Enrich-Error") ?? undefined })
        else { let d = xhr.statusText; try { d = JSON.parse(xhr.responseText).detail ?? d } catch { /* ignore */ } reject(new Error(typeof d === "string" ? d : JSON.stringify(d))) }
      }
      xhr.onerror = () => reject(new Error("upload failed"))
      xhr.send(form)
    }),
}

export const lab = {
  list: () => req<LabVideo[]>("/lab/videos"),
  get: (id: string) => req<LabVideo>(`/lab/videos/${id}`),
  create: (body: { prompt: string; target_duration: number; style?: string | null }) => req<LabVideo>("/lab/videos", { method: "POST", body: JSON.stringify(body) }),
  generateImages: (id: string, onlyMissing = false) => req<unknown>(`/lab/videos/${id}/generate-images${onlyMissing ? "?only_missing=true" : ""}`, { method: "POST" }),
  regenerate: (id: string, index: number, prompt?: string | null) => req<unknown>(`/lab/videos/${id}/keyframes/${index}/regenerate`, { method: "POST", body: JSON.stringify({ prompt: prompt ?? null }) }),
  animate: (id: string) => req<unknown>(`/lab/videos/${id}/animate`, { method: "POST" }),
  delete: (id: string) => req<void>(`/lab/videos/${id}`, { method: "DELETE" }),
  imageUrl: (id: string, index: number, v: number) => `${API}/lab/videos/${id}/keyframes/${index}/image?v=${v}`,
  segmentUrl: (id: string, index: number) => `${API}/lab/videos/${id}/segments/${index}/video`,
  videoUrl: (id: string) => `${API}/lab/videos/${id}/video`,
}

export const media = {
  video: (id: string) => `${API}/projects/${id}/video`,
  voice: (id: string) => `${API}/projects/${id}/voice`,
  renderVideo: (id: string, v: number) => `${API}/projects/${id}/renders/${v}/video`,
  assetThumb: (id: string) => `${API}/assets/${id}/thumbnail`,
  assetFile: (id: string) => `${API}/assets/${id}/file`,
}

export const fmtTime = (s: number) => {
  const m = Math.floor(s / 60), r = s - m * 60
  return `${m}:${r.toFixed(1).padStart(4, "0")}`
}
export const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
