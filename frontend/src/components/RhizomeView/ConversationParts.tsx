/**
 * The parts of a conversation view that chat and completion views share:
 * the panels that open under a node, the end of the conversation (first-turn
 * action, streaming, errors), and the context inspector.
 */

import type { NodeResponse } from '../../api/types.ts'
import { useRhizomeData, useRhizomeStore, useStreamingState } from '../../store/rhizomeStore.ts'
import { ContextModal } from './ContextModal.tsx'
import { reconstructContext } from './contextReconstruction.ts'
import { CrossModelPanel } from './CrossModelPanel.tsx'
import { FirstTurnAction } from './FirstTurnAction.tsx'
import { ForkPanel } from './ForkPanel.tsx'
import { GenerationErrorPanel } from './GenerationErrorPanel.tsx'
import { ProbePanel } from './ProbePanel.tsx'
import { ReplayPanel } from './ReplayPanel.tsx'
import { StreamingDisplay } from './StreamingDisplay.tsx'
import { SummarizePanel } from './SummarizePanel.tsx'
import type { useConversationView } from './useViewShared.ts'
import { WriteResponsePanel } from './WriteResponsePanel.tsx'

type View = ReturnType<typeof useConversationView>

/** The fork/regenerate panel, configured for this rhizome and branch. */
export function ForkPanelFor({ view, mode }: { view: View; mode: NonNullable<View['fork']['forkTarget']>['mode'] }) {
  const { currentRhizome, providers } = useRhizomeData()
  const { isGenerating } = useStreamingState()
  const { fork } = view
  return (
    <ForkPanel
      mode={mode}
      onForkSubmit={fork.handleForkSubmit}
      onRegenerateSubmit={fork.handleRegenerateSubmit}
      onPrefillSubmit={fork.handlePrefillSubmit}
      onPrefillContinue={fork.handlePrefillContinue}
      onCancel={() => fork.setForkTarget(null)}
      isGenerating={isGenerating}
      providers={providers}
      defaults={view.branchDefaults}
      streamDefault={currentRhizome?.metadata?.stream_responses !== false}
      samplingDefaults={currentRhizome?.default_sampling_params ?? null}
    />
  )
}

/** Whatever panel is open under this node. */
export function NodePanels({ view, node }: { view: View; node: NodeResponse }) {
  const { providers, currentRhizome } = useRhizomeData()
  const { isGenerating } = useStreamingState()
  const prefillAssistant = useRhizomeStore(s => s.prefillAssistant)
  const { forkTarget } = view.fork
  const open = view.openPanel?.nodeId === node.node_id ? view.openPanel.kind : null

  // Prefill/generate open under the node answered; fork/regenerate under its parent
  const forkHere = !isGenerating && forkTarget != null && (
    forkTarget.mode === 'prefill' || forkTarget.mode === 'generate'
      ? forkTarget.parentId === node.node_id
      : forkTarget.parentId === (node.parent_id ?? '')
  )

  return (
    <>
      {forkHere && <ForkPanelFor view={view} mode={forkTarget.mode} />}
      {open === 'summarize' && <SummarizePanel nodeId={node.node_id} onClose={view.closePanel} />}
      {open === 'probe' && currentRhizome && (
        <ProbePanel
          rhizomeId={currentRhizome.rhizome_id}
          nodeId={node.node_id}
          provider={view.branchDefaults.provider}
          model={view.branchDefaults.model}
          onClose={view.closePanel}
        />
      )}
      {open === 'replay' && (() => {
        const from = view.path.findIndex((n) => n.node_id === node.node_id)
        if (from === -1) return null
        const preview = (node.content || '').slice(0, 40) + (node.content.length > 40 ? '...' : '')
        return (
          <ReplayPanel
            pathNodeIds={view.path.slice(from).map((n) => n.node_id)}
            pathDescription={`From "${preview}"`}
            onCancel={view.closePanel}
            providers={providers}
            defaults={view.branchDefaults}
          />
        )
      })()}
      {open === 'crossModel' && (
        <CrossModelPanel
          nodeId={node.node_id}
          onCancel={view.closePanel}
          isGenerating={isGenerating}
          providers={providers}
          defaults={{ provider: view.branchDefaults.provider, model: view.branchDefaults.model }}
        />
      )}
      {open === 'writeResponse' && (
        <WriteResponsePanel
          onSubmit={(content) => {
            prefillAssistant(node.node_id, content)
            view.closePanel()
          }}
          onCancel={view.closePanel}
        />
      )}
    </>
  )
}

/** After the last node: the first-turn action, the live stream, a failed generation. */
export function ConversationEnd({ view, showFirstTurn = true }: { view: View; showFirstTurn?: boolean }) {
  const {
    isGenerating, streamingContent, streamingThinkingContent,
    streamingContents, streamingThinkingContents, streamingNodeIds,
    streamingTotal, activeStreamIndex, generationError, stopGeneration,
  } = useStreamingState()
  const setActiveStreamIndex = useRhizomeStore(s => s.setActiveStreamIndex)
  const regenerate = useRhizomeStore(s => s.regenerate)
  const clearGenerationError = useRhizomeStore(s => s.clearGenerationError)
  const openSteer = useRhizomeStore(s => s.openSteer)
  const { forkTarget, setForkTarget } = view.fork

  return (
    <>
      {showFirstTurn && view.path.length === 0 && !isGenerating && (
        <FirstTurnAction
          open={forkTarget?.parentId === ''}
          onOpen={() => setForkTarget({ parentId: '', mode: 'generate' })}
          onSteer={() => openSteer('')}
          panel={<ForkPanelFor view={view} mode={forkTarget?.mode ?? 'generate'} />}
        />
      )}

      <StreamingDisplay
        isGenerating={isGenerating}
        streamingContent={streamingContent}
        streamingThinkingContent={streamingThinkingContent}
        streamingContents={streamingContents}
        streamingThinkingContents={streamingThinkingContents}
        streamingNodeIds={streamingNodeIds}
        streamingTotal={streamingTotal}
        activeStreamIndex={activeStreamIndex}
        setActiveStreamIndex={setActiveStreamIndex}
        stopGeneration={stopGeneration}
      />

      {!isGenerating && generationError && (
        <GenerationErrorPanel
          generationError={generationError}
          leafNodeId={view.leafNodeId}
          onRetry={regenerate}
          onChangeSettings={setForkTarget}
          onDismiss={clearGenerationError}
        />
      )}
    </>
  )
}

/** "What the model saw" for the inspected node. */
export function InspectedContext({ nodes }: { nodes: NodeResponse[] }) {
  const inspectedNodeId = useRhizomeStore(s => s.inspectedNodeId)
  const setInspectedNodeId = useRhizomeStore(s => s.setInspectedNodeId)
  const node = inspectedNodeId ? nodes.find((n) => n.node_id === inspectedNodeId) : undefined
  if (!node) return null
  return (
    <ContextModal
      context={reconstructContext(node, nodes)}
      onDismiss={() => setInspectedNodeId(null)}
    />
  )
}
