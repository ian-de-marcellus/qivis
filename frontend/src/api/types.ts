/** TypeScript interfaces matching backend Pydantic schemas. */

// -- Responses --

export interface TreeSummary {
  tree_id: string
  title: string | null
  conversation_mode: string
  created_at: string
  updated_at: string
}

export interface NodeResponse {
  node_id: string
  tree_id: string
  parent_id: string | null
  role: string
  content: string
  model: string | null
  provider: string | null
  system_prompt: string | null
  sampling_params: Record<string, unknown> | null
  mode: string | null
  usage: Record<string, number> | null
  latency_ms: number | null
  finish_reason: string | null
  logprobs: Record<string, unknown> | null
  context_usage: ContextUsage | null
  participant_id: string | null
  participant_name: string | null
  created_at: string
  archived: number
}

export interface ContextUsage {
  total_tokens: number
  max_tokens: number
  breakdown: Record<string, number>
  excluded_tokens: number
  excluded_count: number
}

export interface TreeDetail {
  tree_id: string
  title: string | null
  metadata: Record<string, unknown>
  default_model: string | null
  default_provider: string | null
  default_system_prompt: string | null
  default_sampling_params: Record<string, unknown> | null
  conversation_mode: string
  created_at: string
  updated_at: string
  archived: number
  nodes: NodeResponse[]
}

// -- Requests --

export interface CreateTreeRequest {
  title?: string
  default_system_prompt?: string
  default_model?: string
  default_provider?: string
}

export interface CreateNodeRequest {
  content: string
  role?: 'system' | 'user' | 'assistant' | 'tool' | 'researcher_note'
  parent_id?: string
}

export interface GenerateRequest {
  provider?: string
  model?: string
  system_prompt?: string
  sampling_params?: Record<string, unknown>
  stream?: boolean
}

// -- SSE events --

export interface TextDeltaEvent {
  type: 'text_delta'
  text: string
}

export interface MessageStopEvent {
  type: 'message_stop'
  content: string
  finish_reason: string | null
  usage: Record<string, number> | null
  latency_ms: number | null
  node_id: string | null
}

export type SSEEvent = TextDeltaEvent | MessageStopEvent
