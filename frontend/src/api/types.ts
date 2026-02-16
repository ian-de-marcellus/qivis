/** TypeScript interfaces matching backend Pydantic schemas. */

// -- Canonical data structures --

export interface SamplingParams {
  temperature?: number | null
  top_p?: number | null
  top_k?: number | null
  max_tokens?: number
  stop_sequences?: string[] | null
  frequency_penalty?: number | null
  presence_penalty?: number | null
  logprobs?: boolean
  top_logprobs?: number | null
  extended_thinking?: boolean
  thinking_budget?: number | null
}

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
  sampling_params: SamplingParams | null
  mode: string | null
  usage: Record<string, number> | null
  latency_ms: number | null
  finish_reason: string | null
  logprobs: LogprobData | null
  thinking_content: string | null
  context_usage: ContextUsage | null
  participant_id: string | null
  participant_name: string | null
  created_at: string
  archived: number
  sibling_count: number
  sibling_index: number
}

export interface ContextUsage {
  total_tokens: number
  max_tokens: number
  breakdown: Record<string, number>
  excluded_tokens: number
  excluded_count: number
}

export interface AlternativeToken {
  token: string
  logprob: number
  linear_prob: number
}

export interface TokenLogprob {
  token: string
  logprob: number
  linear_prob: number
  top_alternatives: AlternativeToken[]
}

export interface LogprobData {
  tokens: TokenLogprob[]
  provider_format: string
  top_k_available: number
}

export interface TreeDetail {
  tree_id: string
  title: string | null
  metadata: Record<string, unknown>
  default_model: string | null
  default_provider: string | null
  default_system_prompt: string | null
  default_sampling_params: SamplingParams | null
  conversation_mode: string
  created_at: string
  updated_at: string
  archived: number
  nodes: NodeResponse[]
}

export interface ProviderInfo {
  name: string
  available: boolean
  models: string[]
  supported_params: string[]
}

// -- Requests --

export interface CreateTreeRequest {
  title?: string
  default_system_prompt?: string
  default_model?: string
  default_provider?: string
}

export interface PatchTreeRequest {
  title?: string | null
  metadata?: Record<string, unknown>
  default_model?: string | null
  default_provider?: string | null
  default_system_prompt?: string | null
  default_sampling_params?: SamplingParams | null
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
  sampling_params?: SamplingParams
  stream?: boolean
  n?: number
}

// -- SSE events --

export interface TextDeltaEvent {
  type: 'text_delta'
  text: string
  completion_index?: number
}

export interface ThinkingDeltaEvent {
  type: 'thinking_delta'
  thinking: string
  completion_index?: number
}

export interface MessageStopEvent {
  type: 'message_stop'
  content: string
  finish_reason: string | null
  usage: Record<string, number> | null
  latency_ms: number | null
  node_id: string | null
  thinking_content: string | null
  completion_index?: number
}

export interface GenerationCompleteEvent {
  type: 'generation_complete'
}

export type SSEEvent = TextDeltaEvent | ThinkingDeltaEvent | MessageStopEvent | GenerationCompleteEvent
