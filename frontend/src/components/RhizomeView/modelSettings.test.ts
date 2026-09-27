import { describe, expect, it } from 'vitest'
import type { ModelEntry, ProviderInfo } from '../../api/types.ts'
import { describeModel, findModel } from '../shared/modelChoice.ts'
import { effectiveMode } from './generationMode.ts'
import { detectPreset } from './samplingPresets.ts'

const provider = (supported_modes: string[]) => ({ supported_modes }) as ProviderInfo

describe('effectiveMode', () => {
  it('sends a mode only to providers that support both', () => {
    expect(effectiveMode(provider(['chat', 'completion']), 'completion')).toBe('completion')
    expect(effectiveMode(provider(['completion']), 'completion')).toBeUndefined()
    expect(effectiveMode(provider(['chat', 'completion']), '')).toBeUndefined()
  })
})

describe('model choice', () => {
  const sun = {
    id: 'llamacpp:sun.gguf', label: 'Sun 1.0.1', provider: 'llamacpp', model: 'sun.gguf',
    mode: 'completion', prompt_template: 'llama3', source: 'profile',
  } as ModelEntry
  it('finds catalog entries and says what the model brings', () => {
    expect(findModel([sun], { provider: 'llamacpp', model: 'sun.gguf' })).toBe(sun)
    expect(findModel([sun], { provider: 'openai', model: 'sun.gguf' })).toBeUndefined()
    expect(describeModel(sun)).toBe("completion · llama3 · from Sun 1.0.1's profile")
  })
})

describe('detectPreset', () => {
  const blank = { temperature: '', topP: '', topK: '', frequencyPenalty: '', presencePenalty: '' }
  it('names the preset the fields match, else custom', () => {
    expect(detectPreset(blank)).toBe('default')
    expect(detectPreset({ ...blank, temperature: '0.7' })).toBe('balanced')
    expect(detectPreset({ ...blank, temperature: '0', topP: '1' })).toBe('deterministic')
    expect(detectPreset({ ...blank, temperature: '0.7', topK: '40' })).toBe('custom')
  })
})
