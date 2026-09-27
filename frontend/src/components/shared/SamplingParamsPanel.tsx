import { PRESET_FIELDS, SAMPLING_PRESETS, detectPreset, type PresetName } from '../RhizomeView/samplingPresets.ts'
import './SamplingParamsPanel.css'

export interface SamplingParamValues {
  temperature: string
  topP: string
  topK: string
  maxTokens: string
  frequencyPenalty: string
  presencePenalty: string
  useThinking: boolean
  thinkingBudget: string
}

interface SamplingParamsPanelProps {
  values: SamplingParamValues
  onChange: (field: keyof SamplingParamValues, value: string | boolean) => void
  supportedParams: string[]
  providerName?: string
  /** "preset" for basics, "details" for an Advanced section, "all" (default) for both. */
  section?: 'preset' | 'details' | 'all'
}

export function SamplingParamsPanel({
  values,
  onChange,
  supportedParams,
  providerName,
  section = 'all',
}: SamplingParamsPanelProps) {
  const isSupported = (param: string) =>
    supportedParams.length === 0 || supportedParams.includes(param)

  const unsupportedTitle = (param: string) =>
    isSupported(param) ? undefined : `Not supported by ${providerName}`

  const currentPreset = detectPreset(values)

  const handlePresetChange = (presetName: PresetName) => {
    if (presetName === 'custom') return
    const preset = SAMPLING_PRESETS[presetName]
    if (!preset) return
    for (const [field, key] of PRESET_FIELDS) {
      onChange(field, preset[key] != null ? String(preset[key]) : '')
    }
  }

  const presetRow = (
      <div className="sampling-params-field">
        <label>Preset</label>
        <select
          value={currentPreset}
          onChange={(e) => handlePresetChange(e.target.value as PresetName)}
        >
          {Object.entries(SAMPLING_PRESETS).map(([key, p]) => (
            <option key={key} value={key}>{p.label}</option>
          ))}
          <option value="custom">Custom</option>
        </select>
      </div>
  )
  if (section === 'preset') return presetRow

  return (
    <>
      {section === 'all' && presetRow}

      <div className="sampling-params-pair">
        <div className={`sampling-params-field${isSupported('temperature') ? '' : ' unsupported-param'}`}>
          <label>Temperature</label>
          <input
            type="number"
            step="0.05"
            min="0"
            max="2"
            value={values.temperature}
            onChange={(e) => onChange('temperature', e.target.value)}
            placeholder="default"
            disabled={!isSupported('temperature')}
            title={unsupportedTitle('temperature')}
          />
        </div>
        <div className={`sampling-params-field${isSupported('top_p') ? '' : ' unsupported-param'}`}>
          <label>Top P</label>
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={values.topP}
            onChange={(e) => onChange('topP', e.target.value)}
            placeholder="default"
            disabled={!isSupported('top_p')}
            title={unsupportedTitle('top_p')}
          />
        </div>
      </div>

      <div className="sampling-params-pair">
        <div className={`sampling-params-field${isSupported('top_k') ? '' : ' unsupported-param'}`}>
          <label>Top K</label>
          <input
            type="number"
            step="1"
            min="0"
            value={values.topK}
            onChange={(e) => onChange('topK', e.target.value)}
            placeholder="default"
            disabled={!isSupported('top_k')}
            title={unsupportedTitle('top_k')}
          />
        </div>
        <div className={`sampling-params-field${isSupported('max_tokens') ? '' : ' unsupported-param'}`}>
          <label>Max tokens</label>
          <input
            type="number"
            step="256"
            min="1"
            value={values.maxTokens}
            onChange={(e) => onChange('maxTokens', e.target.value)}
            placeholder="2048"
            disabled={!isSupported('max_tokens')}
            title={unsupportedTitle('max_tokens')}
          />
        </div>
      </div>

      <div className="sampling-params-pair">
        <div className={`sampling-params-field${isSupported('frequency_penalty') ? '' : ' unsupported-param'}`}>
          <label>Freq penalty</label>
          <input
            type="number"
            step="0.1"
            min="-2"
            max="2"
            value={values.frequencyPenalty}
            onChange={(e) => onChange('frequencyPenalty', e.target.value)}
            placeholder="default"
            disabled={!isSupported('frequency_penalty')}
            title={unsupportedTitle('frequency_penalty')}
          />
        </div>
        <div className={`sampling-params-field${isSupported('presence_penalty') ? '' : ' unsupported-param'}`}>
          <label>Pres penalty</label>
          <input
            type="number"
            step="0.1"
            min="-2"
            max="2"
            value={values.presencePenalty}
            onChange={(e) => onChange('presencePenalty', e.target.value)}
            placeholder="default"
            disabled={!isSupported('presence_penalty')}
            title={unsupportedTitle('presence_penalty')}
          />
        </div>
      </div>

      <div className={`sampling-params-toggle${isSupported('extended_thinking') ? '' : ' unsupported-param'}`}>
        <label>
          <input
            type="checkbox"
            checked={values.useThinking}
            onChange={(e) => onChange('useThinking', e.target.checked)}
            disabled={!isSupported('extended_thinking')}
          />
          Extended thinking
        </label>
        {!isSupported('extended_thinking') && (
          <span className="unsupported-hint" title={unsupportedTitle('extended_thinking')}>unsupported</span>
        )}
      </div>

      {values.useThinking && isSupported('extended_thinking') && (
        <div className="sampling-params-field">
          <label>Thinking budget</label>
          <input
            type="number"
            min="1024"
            step="1024"
            value={values.thinkingBudget}
            onChange={(e) => onChange('thinkingBudget', e.target.value)}
            placeholder="10000"
          />
        </div>
      )}
    </>
  )
}
