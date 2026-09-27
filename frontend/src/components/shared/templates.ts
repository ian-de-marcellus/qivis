/** Completion-mode prompt templates, for the settings menus. */

export const TEMPLATE_OPTIONS: { value: string; label: string }[] = [
  { value: 'transcript', label: 'Transcript (base models: "Name: …" turns)' },
  { value: 'document', label: 'Document (base models: one continuous text)' },
  { value: 'raw', label: 'Raw (turns on separate lines, no names)' },
  { value: 'llama3', label: 'Llama 3' },
  { value: 'chatml', label: 'ChatML' },
  { value: 'alpaca', label: 'Alpaca' },
]

export const DEFAULT_SPEAKER = 'Person'
export const DEFAULT_MODEL_NAME = 'Sun'
