export type ProjectStatus =
  | "DRAFT" | "GENERATING_SCRIPT" | "GENERATING_VOICE" | "PLANNING" | "SELECTING_ASSETS"
  | "GENERATING_CAPTIONS" | "RENDERING" | "READY" | "APPROVED" | "FAILED"

export const STAGES: { key: ProjectStatus; label: string }[] = [
  { key: "GENERATING_SCRIPT", label: "Script" },
  { key: "GENERATING_VOICE", label: "Voice" },
  { key: "PLANNING", label: "Scenes" },
  { key: "SELECTING_ASSETS", label: "B-roll" },
  { key: "GENERATING_CAPTIONS", label: "Captions" },
  { key: "RENDERING", label: "Render" },
  { key: "READY", label: "Ready" },
]

export interface Scene {
  order: number; section: string | null; start_time: number; end_time: number
  asset_id: string | null; asset_start_time: number; overlay_text: string | null; intent: string | null
}
export interface RenderInfo {
  id: string; version: number; plan_version: number; voice_version: number; status: string
  output_path: string | null; qc: { passed: boolean; failures: string[]; info: Record<string, unknown> } | null
  error: string | null; created_at: string
}
export interface EventInfo { stage: string; level: string; message: string; created_at: string }
export interface Project {
  id: string; persona_id: string; template_id: string; topic: string; target_duration: number
  actual_duration: number | null; status: ProjectStatus; stage_message: string | null; error: string | null
  script: string | null; script_version: number; voice_version: number; plan_version: number; render_version: number
  current_render_id: string | null; created_at: string; updated_at: string; approved_at: string | null
  scenes: Scene[]; renders: RenderInfo[]; events: EventInfo[]; video_url: string | null
}
export interface Asset {
  id: string; file: string; description: string | null; tags: string[]; action: string | null; location: string | null
  shot: string | null; mood: string | null; duration: number; width: number | null; height: number | null; fps: number | null
  orientation: string | null; usable_start: number; usable_end: number; quality_score: number; usage_count: number
  last_used_at: string | null; approved: boolean
}
export interface Candidate {
  asset_id: string; description: string | null; tags: string[]; action: string | null; location: string | null
  shot: string | null; mood: string | null; duration: number; score: number; recently_used: boolean
}
export interface Template {
  id: string; name: string; description: string; duration: { min: number; target: number; max: number }
  sections: { type: string; weight: number; guidance: string }[]; voiceover: boolean; caption_style: string
  music_category: string | null; closing: string | null; shot_duration: { min: number; max: number }; overlays: { min: number; max: number }
}
export interface Persona {
  id: string; name: string; language: string; audience: string; topics: string[]; tone: string[]; avoid: string[]
  identity?: { name: string; age?: number; location?: string; background?: string } | null
  tools: string[]; products: { name: string; one_liner: string }[]; product_mention_policy: string; closing_style: string
  target_duration: number; max_duration: number; speech_rate_wps: number
  voice: { provider: string; voice_id: string; model_id: string; speed: number; stability: number; similarity_boost: number }
}
export interface CaptionChunk { start: number; end: number; text: string; emphasis_index: number | null }
export interface PlanScene { order: number; start: number; end: number; asset_id: string; asset_file: string; asset_start: number; text: string | null; section: string | null }
export interface Plan {
  version: string; persona: string; template: string; topic: string
  voiceover: { text: string; audio: string; duration: number }; scenes: PlanScene[]; caption_style: string
  music: string | null; captions: CaptionChunk[]; seed: number
}
export interface Artifacts {
  scripts: { version: number; content: { hook: string; sections: { type: string; text: string }[]; notes?: string | null } }[]
  voices: { version: number; script_version: number; duration: number; provider: string; url: string }[]
  plans: (Plan & { version: number })[]
  renders: (RenderInfo & { url: string | null; seed: number })[]
}
export interface SystemInfo {
  llm_provider: string; openai_model: string; openai_key_set: boolean; voice_provider: string; elevenlabs_key_set: boolean
  elevenlabs_voice_id_set: boolean; default_persona: string; database_url: string; assets_dir: string; storage_dir: string
  ffmpeg: string; render_ok: boolean; render_missing: string[]; assets_count: number; assets_approved: number
  projects_count: number; music_tracks: string[]
}

export interface ClipAnalysis {
  description: string; tags: string[]; action: string; location: string; shot: string; mood: string
  suggested_category: string; quality_score: number; notes: string | null
  duration: number; width: number; height: number; fps: number; usable_start: number; usable_end: number
  frames_analyzed: number; categories: string[]
}
