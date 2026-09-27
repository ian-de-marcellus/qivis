/** Opens the steering view for the store's steer target, with a model that can be steered. */

import { useState } from 'react'
import { getActivePath, useRhizomeData, useRhizomeStore } from '../../store/rhizomeStore.ts'
import { SteerView } from './SteerView.tsx'

// Steering needs next-token distributions, which only llama.cpp serves for now
const STEERABLE = 'llamacpp'

export function SteerHost() {
  const { currentRhizome, models } = useRhizomeData()
  const steerTarget = useRhizomeStore(s => s.steerTarget)
  const closeSteer = useRhizomeStore(s => s.closeSteer)
  const [picked, setPicked] = useState<string | null>(null)

  if (steerTarget == null || !currentRhizome) return null

  const options = models.filter((m) => m.provider === STEERABLE).map((m) => m.model)
  // The branch's own local model if it has one, else the rhizome's, else the first local one
  const path = getActivePath(currentRhizome.nodes, useRhizomeStore.getState().branchSelections)
  const branchModel = [...path].reverse().find((n) => n.provider === STEERABLE)?.model
  const rhizomeModel = currentRhizome.default_provider === STEERABLE ? currentRhizome.default_model : null
  const model = picked ?? branchModel ?? rhizomeModel ?? options[0]

  const close = () => {
    setPicked(null)
    closeSteer()
  }

  if (!model) {
    return (
      <div className="steer-overlay" onClick={close}>
        <div className="steer-panel steer-empty">
          No local (llama.cpp) model is available to steer. Start one and try again.
        </div>
      </div>
    )
  }

  return (
    <SteerView
      key={`${steerTarget}:${model}`}
      rhizomeId={currentRhizome.rhizome_id}
      parentId={steerTarget || null}
      parentRole={currentRhizome.nodes.find((n) => n.node_id === steerTarget)?.role ?? null}
      provider={STEERABLE}
      model={model}
      modelOptions={options.includes(model) ? options : [model, ...options]}
      onModelChange={setPicked}
      onClose={close}
    />
  )
}
