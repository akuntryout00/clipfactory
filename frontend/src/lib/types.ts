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
  caption_overrides: CaptionOverrides | null; caption_style: CaptionStyle | null; batch_id?: string | null
}
export type BatchStatus = "PENDING" | "RUNNING" | "DONE" | "CANCELLED" | "FAILED"
export interface Batch {
  id: string; persona_id: string; name: string; status: BatchStatus; total: number; done: number; failed: number; running: number
  pending: number; approved: number; config: { count?: number; template_ids?: string[] | null; topics_source?: string; target_duration?: number | null }
  error: string | null; cancel_requested: boolean; created_at: string; updated_at: string; finished_at: string | null
  projects?: Project[]
}
/** font / size / position overrides; null = keep the template's caption style */
export interface CaptionOverrides {
  font_name?: string | null; font_size?: number | null; bold?: boolean | null; vertical_anchor_ratio?: number | null
  overlay_font_name?: string | null; overlay_font_size?: number | null; overlay_vertical_anchor_ratio?: number | null
}
export interface CaptionStyle {
  id: string; font_name: string; font_size: number; bold: boolean; primary_color: string; emphasis_color: string; outline_color: string
  outline: number; shadow: number; max_chars_per_line: number; vertical_anchor_ratio: number; animation: string
  safe_zone: { top: number; bottom: number; left: number; right: number }
  overlay: { font_name: string; font_size: number; bold: boolean; primary_color: string; outline_color: string; outline: number; vertical_anchor_ratio: number; max_chars_per_line: number }
}
export interface FontInfo { family: string; style: string | null; file: string | null; source: "fonts_dir" | "system"; line_factor?: number | null }
export interface Asset {
  id: string; file: string; description: string | null; tags: string[]; action: string | null; location: string | null
  shot: string | null; mood: string | null; duration: number; width: number | null; height: number | null; fps: number | null
  orientation: string | null; usable_start: number; usable_end: number; quality_score: number; usage_count: number
  last_used_at: string | null; approved: boolean; persona_id: string | null; shotlist_item_id?: string | null
}
export interface ShotlistItem {
  id: string; order: number; category: string; title: string; description: string; shot: string | null; action: string | null
  location: string | null; mood: string | null; tags: string[]; count: number; filled: number; done: boolean
  assets: { id: string; file: string; approved: boolean }[]
}
export interface Shotlist {
  persona_id: string; target_count: number | null; generated_at: string | null; guidance: string | null; model: string | null
  wanted: number; filled: number; percent: number; items_total: number; items_done: number; library_count: number
  unassigned_count: number; unassigned_asset_ids: string[]; items: ShotlistItem[]; matched?: number
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
export type ProductPolicy = "never" | "occasional_soft" | "problem_solution_only"
export type ClosingStyle = "punchline_no_cta" | "question" | "soft_follow"
export interface PersonaIdentity { name: string; age?: number | null; location?: string | null; background?: string | null; speaks_as?: string }
export interface PersonaVoice { provider: string; voice_id: string; model_id: string; speed: number; stability: number; similarity_boost: number; style: number; voice_id_set?: boolean }
export interface Persona {
  id: string; name: string; language: string; audience: string; topics: string[]; tone: string[]; avoid: string[]
  identity?: PersonaIdentity | null
  tools: string[]; products: { name: string; one_liner: string }[]; product_mention_policy: ProductPolicy; closing_style: ClosingStyle
  target_duration: number; max_duration: number; speech_rate_wps: number
  voice: PersonaVoice; default_music_category?: string | null
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
export interface ProviderField { set: boolean; source: "ui" | "env" | null; value: string | null; secret: boolean }
export interface ProviderSettings {
  fields: Record<string, ProviderField>; configured: boolean; setup_required: boolean; missing: string[]
  llm_provider: string; voice_provider: string; lab_ready: boolean
}
export interface ProviderTestResult { ok: boolean; message: string; voices?: { id: string; name: string; labels?: Record<string, string> }[] }
export interface SystemInfo {
  configured?: boolean; setup_required?: boolean; missing?: string[]
  llm_provider: string; openai_model: string; openai_key_set: boolean; voice_provider: string; elevenlabs_key_set: boolean
  elevenlabs_voice_id_set: boolean; default_persona: string; database_url: string; assets_dir: string; storage_dir: string; fonts_dir?: string
  ffmpeg: string; render_ok: boolean; render_missing: string[]; assets_count: number; assets_approved: number
  projects_count: number; music_tracks: string[]
  lab?: { planner: string; image_provider: string; image_model: string; image_size: string; video_provider: string; video_model: string; google_key_set: boolean; fal_key_set?: boolean; fal_default_model?: string }
}

export interface ClipAnalysis {
  description: string; tags: string[]; action: string; location: string; shot: string; mood: string
  suggested_category: string; quality_score: number; notes: string | null
  duration: number; width: number; height: number; fps: number; usable_start: number; usable_end: number
  frames_analyzed: number; categories: string[]
}

// ---- AI Lab (isolated module) ----
export interface LabKeyframe { index: number; prompt: string; caption: string | null; status: string; error: string | null; version: number; image_url: string | null }
export interface LabSegment { index: number; from_index: number; to_index: number; prompt: string | null; status: string; error: string | null; duration: number | null; video_url: string | null; editable: boolean; last_edit: string | null; version: number }
export interface LabProvider { id: string; label: string; vendor: string; model: string; max_seconds: number; min_seconds: number; supports_edit: boolean; first_last: boolean; audio: boolean; price_hint: string | null; price_per_second: number; note: string | null; available: boolean; needs: string | null }
export interface LabEstimate { provider: string; label: string; target_duration: number; n_segments: number; segment_seconds: number; video_seconds: number; keyframes: number; price_per_second: number; video_cost: number; image_cost: number; per_image: number; image_quality: string; planner_cost: number; total: number; note: string }
export interface LabEvent { stage: string; level: "info" | "success" | "warning" | "error" | string; message: string; created_at: string }
export interface LabVideo {
  id: string; prompt: string; style: string | null; target_duration: number; n_segments: number; segment_seconds: number; style_guide: string | null
  status: string; stage_message: string | null; error: string | null; final_duration: number | null; image_model: string | null; video_model: string | null
  video_provider: string | null; provider_label: string | null; supports_edit: boolean
  created_at: string; updated_at: string; keyframes: LabKeyframe[]; segments: LabSegment[]; video_url: string | null; events: LabEvent[]
}
