const BASE = 'http://localhost:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  status: () => request<{ events_in_memory: number; status: string }>('/api/status'),

  events: (category?: string) =>
    request<{ events: MarketEvent[]; total: number }>(
      `/api/events${category ? `?category=${category}` : ''}`
    ),

  preview: (category?: string, limit = 8) =>
    request<{ events: MarketEvent[]; total: number }>(
      `/api/preview?limit=${limit}${category ? `&category=${category}` : ''}`
    ),

  remember: (body: { source?: string; category?: string; max_events: number }) =>
    request<RememberResult>('/api/remember', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  recall: (body: { market_id?: string; market_question?: string; category?: string }) =>
    request<RecallResult>('/api/recall', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  analyze: (body: {
    market_id?: string
    market_question?: string
    category?: string
    odds_after?: number
  }) =>
    request<AnalyzeResult>('/api/analyze', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  improve: (body: {
    market_id: string
    actual_outcome: string
    feedback_score?: number
    feedback_text?: string
  }) =>
    request<ImproveResult>('/api/improve', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  forget: (body: { dry_run: boolean; min_feedbacks: number; max_score: number }) =>
    request<ForgetResult>('/api/forget', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}

// ── types ───────────────────────────────────────────────────────────────────

export interface MarketEvent {
  market_id: string
  market_question: string
  category: string
  odds_before?: number
  odds_after?: number
  odds_move_pct?: number
  timestamp?: string
  outcome?: string
  outcome_date?: string
  narrative?: string
}

export interface RememberResult {
  events_ingested: number
  dataset_name: string
  status: string
  elapsed_seconds: number
}

export interface RecallResult {
  query: string
  chunks: string[]
  qa_id?: string
  n_stored: number
}

export interface AnalyzeResult {
  new_event: MarketEvent
  chunks: string[]
  brief: string
  qa_id?: string
}

export interface FeedbackEntry {
  qa_id: string
  score: number
  reasoning: string
  feedback_text: string
  add_feedback_returned: boolean
  original_answer_chars: number
}

export interface ImproveResult {
  market_id: string
  actual_outcome: string
  qa_ids_found: number
  feedback_results: FeedbackEntry[]
  note?: string
}

export interface ForgetCandidate {
  market_id: string
  avg_score: number
  feedback_count: number
  scores: number[]
  reason: string
}

export interface ForgetResult {
  candidates: ForgetCandidate[]
  dataset_id: string | null
  pruned: Array<{ market_id: string; data_id: string; dry_run?: boolean }>
  not_found: string[]
  dry_run: boolean
}
