export type Channel = 'linkedin' | 'email' | 'whatsapp'
export type JobType = 'scrape' | 'personalize'
export type JobStatus =
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'blocked_auth'
  | 'rate_limited'
export type RowStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'done'
  | 'failed'
  | 'skipped'
  | 'thin_context'
  | 'needs_review'

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
  /** Only while status is rate_limited: when the worker restarts the job. */
  resume_at: string | null
  /** All tokens the job's rows used. */
  tokens: number
  /** Each pause for a limit: when, why, and when it resumed. */
  limit_events: { at: string; reason: string; resume_at: string | null }[]
  /** Leads of this upload still waiting for the background LinkedIn check. */
  linkedin_pending: number
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
  /** The full message. Null for a row written in line-only mode. */
  body: string | null
  /** The personal statement, a column of its own. */
  personal_line: string | null
  output_mode: 'full_message' | 'personalized_line'
  angle: string | null
  evidence: string | null
  /** What to do with a personalized row: personalised, generic, hold, or empty. */
  outreach: '' | 'personalised' | 'generic' | 'hold'
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
  /** Copy for rows whose research does not show the prospect has the problem. */
  fallback_body: string
  constraints: Constraints
  version: number
  is_active: boolean
  created_at: string
}

export interface Objection {
  objection: string
  response: string
}

export interface AgentProfile {
  offer: string
  what_we_do: string
  icp: string
  proof_points: string[]
  voice: string
  sample_messages: string[]
  objections: Objection[]
  qualification: string
  booking_link: string
  never_claim: string[]
  relevance_terms: string[]
  output_mode: 'full_message' | 'personalized_line'
  compact_research: boolean
}

export interface Agent {
  id: string
  lineage_id: string
  name: string
  profile: AgentProfile
  version: number
  is_active: boolean
  created_at: string
}

export interface ChatAttachment {
  name: string
  text: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  attachments?: ChatAttachment[]
}

/** One server-sent event of an agent chat turn. */
export type ChatEvent =
  | { type: 'delta'; text: string }
  | { type: 'reply_done' }
  | { type: 'profile'; profile: AgentProfile; missing: string[]; done: boolean }
  | { type: 'done' }
  | { type: 'error'; message: string }

export interface AiStatus {
  mode: 'oauth' | 'api_key' | 'claude_code'
  connected: boolean
  detail: string
  organization: string | null
  workspace: string | null
  ant_installed: boolean
  claude_code_installed: boolean
  api_key_in_env: boolean
  warning: string | null
  model: string
}

export interface AppSettings {
  ai: {
    mode: 'oauth' | 'api_key' | 'claude_code'
    model: string
    stage_models: Record<string, string>
    effort: Record<string, string>
    enabled_stages: number[]
    max_tokens: number
    personalization_output_mode?: 'full_message' | 'personalized_line'
    compact_research?: boolean
    relevance_terms?: string[]
  }
  provider_keys: Record<string, string | null>
  enabled_sources: string[]
  concurrency: number
  offer_context: string
  linkedin_provider: string
  linkedin_daily_limit: number
  linkedin_reads_per_hour: number
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
  draft: { subject: string | null; body: string; personal_line?: string | null } | null
  fit_established?: boolean | null
  fit_evidence?: string | null
  ask_first?: boolean
  thin_context: boolean
  hold?: boolean
  reason: string
  warnings: string[]
  constraint_warning: string | null
  usage: Record<string, number>
  cost_usd: number
}
