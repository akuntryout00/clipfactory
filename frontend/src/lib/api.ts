import type { Artifacts, Asset, Candidate, Persona, Plan, Project, SystemInfo, Template } from "./types"

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
  importAssets: () => req<{ created: number; updated: number; errors: string[] }>("/assets/import", { method: "POST" }),
  enrichAssets: () => req<{ enriched: number }>("/assets/enrich", { method: "POST" }),
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
