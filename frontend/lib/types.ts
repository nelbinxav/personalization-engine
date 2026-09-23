export type Channel = 'linkedin' | 'email' | 'whatsapp'
export type JobType = 'scrape' | 'personalize'
export type JobStatus =
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'blocked_auth'
export type RowStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'skipped'
  | 'thin_context'

export interface Upload {
  id: string
  name: string
  source: 'csv' | 'gsheet'
  row_count: number
  headers: string[]
  column_mapping: Record<string, string>
  created_at: string
  scraped: number
  personalized: number
}

export interface UploadPreview {
  headers: string[]
  sample_rows: Record<string, string>[]
  row_count: number
  suggested_mapping: Record<string, string>
  staging_id: string
}

export interface JobCounts {
  total: number
  done: number
  failed: number
  skipped: number
}

export interface JobOptions {
  sources: string[]
  channel: Channel | null
  template_id: string | null
  prompt_ids: Record<string, string>
  concurrency: number
  force: boolean
  limit: number | null
}

export interface Job {
  id: string
  type: JobType
  upload_id: string
  upload_name: string | null
  status: JobStatus
  counts: JobCounts
  options: JobOptions
  error: string | null
  cost_usd: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Identity {
  full_name: string | null
  first_name: string | null
  last_name: string | null
  title: string | null
  company: string | null
  website: string | null
  linkedin_url: string | null
  linkedin_company_url: string | null
  email: string | null
  phone: string | null
  location: string | null
}

export interface ProspectRow {
  id: string
  row_index: number
  identity: Identity
  scrape_status: RowStatus
  personalize_status: RowStatus
  scrape_error: string | null
  personalize_error: string | null
  sources: Record<string, boolean>
  subject: string | null
  body: string | null
  angle: string | null
  evidence: string | null
  cost_usd: number
}

export interface Prompt {
  id: string
  stage: number
  name: string
  body: string
  version: number
  is_active: boolean
  created_at: string
}

export interface Constraints {
  max_chars: number | null
  has_subject: boolean
  subject_max_chars: number | null
}

export interface Template {
  id: string
  channel: Channel
  name: string
  body: string
  constraints: Constraints
  version: number
  is_active: boolean
  created_at: string
}

export interface AiStatus {
  mode: 'oauth' | 'api_key'
  connected: boolean
  detail: string
  organization: string | null
  workspace: string | null
  ant_installed: boolean
  api_key_in_env: boolean
  warning: string | null
  model: string
}

export interface AppSettings {
  ai: {
    mode: 'oauth' | 'api_key'
    model: string
    effort: Record<string, string>
    enabled_stages: number[]
    max_tokens: number
  }
  provider_keys: Record<string, string | null>
  enabled_sources: string[]
  concurrency: number
  offer_context: string
  linkedin_provider: string
}

export interface SettingsResponse {
  settings: AppSettings
  catalog: {
    sources: { key: string; label: string }[]
    models: { id: string; label: string }[]
    efforts: string[]
    linkedin_providers: { key: string; label: string; note: string }[]
  }
}

export interface PreviewResult {
  prospect: {
    id: string
    row_index: number
    name: string
    company: string | null
    sources: Record<string, boolean>
  }
  dossier: {
    summary: string
    facts: { text: string; source_key: string }[]
    recent_events: { text: string; source_key: string }[]
    tech_signals: { text: string; source_key: string }[]
  } | null
  angles: { angle: string; evidence: string; source_key: string }[]
  draft: { subject: string | null; body: string } | null
  thin_context: boolean
  reason: string
  warnings: string[]
  constraint_warning: string | null
  usage: Record<string, number>
  cost_usd: number
}
