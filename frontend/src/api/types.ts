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
  edited_content: string | null
  include_thinking_in_context: boolean
  include_timestamps: boolean
  context_usage: ContextUsage | null
  participant_id: string | null
  participant_name: string | null
  created_at: string
  archived: number
  sibling_count: number
  sibling_index: number
  annotation_count: number
  edit_count: number
  is_bookmarked: boolean
  is_excluded: boolean
}

export interface ContextUsage {
  total_tokens: number
  max_tokens: number
  breakdown: Record<string, number>
  excluded_tokens: number
  excluded_count: number
  excluded_node_ids?: string[]
  evicted_node_ids?: string[]
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

export interface EditHistoryEntry {
  event_id: string
  sequence_num: number
  timestamp: string
  new_content: string | null
}

export interface EditHistoryResponse {
  node_id: string
  original_content: string
  current_content: string
  entries: EditHistoryEntry[]
}

export interface InterventionEntry {
  event_id: string
  sequence_num: number
  timestamp: string
  intervention_type: 'node_edited' | 'system_prompt_changed' | 'exclusion_changed'
  node_id: string | null
  original_content: string | null
  new_content: string | null
  old_value: string | null
  new_value: string | null
}

export interface InterventionTimelineResponse {
  tree_id: string
  interventions: InterventionEntry[]
}

export interface AnnotationResponse {
  annotation_id: string
  tree_id: string
  node_id: string
  tag: string
  value: unknown
  notes: string | null
  created_at: string
}

export interface TaxonomyResponse {
  base_tags: string[]
  used_tags: string[]
}

export interface BookmarkResponse {
  bookmark_id: string
  tree_id: string
  node_id: string
  label: string
  notes: string | null
  summary: string | null
  summary_model: string | null
  summarized_node_ids: string[] | null
  created_at: string
}

export interface CreateBookmarkRequest {
  label: string
  notes?: string
}

export interface NodeExclusionResponse {
  tree_id: string
  node_id: string
  scope_node_id: string
  reason: string | null
  created_at: string
}

export interface DigressionGroupResponse {
  group_id: string
  tree_id: string
  label: string
  node_ids: string[]
  included: boolean
  created_at: string
}

export interface CreateDigressionGroupRequest {
  node_ids: string[]
  label: string
  excluded_by_default?: boolean
}

export interface AddAnnotationRequest {
  tag: string
  value?: unknown
  notes?: string
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
  mode?: 'chat' | 'completion' | 'manual'
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
