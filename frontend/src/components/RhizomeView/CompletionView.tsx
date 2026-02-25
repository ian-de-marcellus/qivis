/**
 * CompletionView — renders completion-mode trees.
 *
 * Uses the same shared hooks as ChatView (path computation, auto-scroll,
 * scroll-to-node, branch defaults, fork panel) but renders completion-mode
 * nodes through CompletionNode instead of MessageRow.
 *
 * Omits chat-specific features: ComparisonView, DigressionCreator,
 * edit history highlights, diff summaries, ContextSplitView.
 * Keeps: branch navigation, fork/regenerate, streaming, error recovery,
 * bookmarks, annotations, notes, exclusions.
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { NodeResponse } from '../../api/types.ts'
import { useRhizomeStore, useRhizomeData, useStreamingState, useComparison, useResearchMetadata } from '../../store/rhizomeStore.ts'
import { CompletionNode } from './CompletionNode.tsx'
import { ContextModal } from './ContextModal.tsx'
import { reconstructContext } from './contextReconstruction.ts'
import { ForkPanel } from './ForkPanel.tsx'
import { GenerationErrorPanel } from './GenerationErrorPanel.tsx'
import { MessageRow } from './MessageRow.tsx'
import { StreamingDisplay } from './StreamingDisplay.tsx'
import { SummarizePanel } from './SummarizePanel.tsx'
import { useActivePath, useAutoScroll, useScrollToNode, useBranchDefaults, useForkPanel } from './useViewShared.ts'
import './ChatView.css'

export function CompletionView() {
  const { currentRhizome, providers } = useRhizomeData()
  const {
    isGenerating, streamingContent, streamingThinkingContent,
    streamingContents, streamingThinkingContents, streamingNodeIds,
    streamingTotal, activeStreamIndex, generationError,
    stopGeneration,
  } = useStreamingState()
  const { inspectedNodeId } = useComparison()
  const { bookmarks, exclusions } = useResearchMetadata()
  const digressionGroups = useRhizomeStore(s => s.digressionGroups)

  const selectBranch = useRhizomeStore(s => s.selectBranch)
  const setActiveStreamIndex = useRhizomeStore(s => s.setActiveStreamIndex)
  const regenerate = useRhizomeStore(s => s.regenerate)
  const clearGenerationError = useRhizomeStore(s => s.clearGenerationError)
  const fetchProviders = useRhizomeStore(s => s.fetchProviders)
  const setInspectedNodeId = useRhizomeStore(s => s.setInspectedNodeId)
  const addBookmark = useRhizomeStore(s => s.addBookmark)
  const removeBookmark = useRhizomeStore(s => s.removeBookmark)
  const excludeNode = useRhizomeStore(s => s.excludeNode)
  const includeNode = useRhizomeStore(s => s.includeNode)
  const toggleAnchor = useRhizomeStore(s => s.toggleAnchor)
  const editNodeContent = useRhizomeStore(s => s.editNodeContent)

  const bottomRef = useRef<HTMLDivElement>(null)
  const [summarizeTargetId, setSummarizeTargetId] = useState<string | null>(null)

  // Shared hooks
  const { nodes, path, childMap, leafNodeId } = useActivePath()
  useAutoScroll(bottomRef)
  useScrollToNode()
  const branchDefaults = useBranchDefaults(path)
  const {
    forkTarget, setForkTarget,
    handleFork, handleForkSubmit, handleRegenerateSubmit,
    handlePrefillSubmit, handlePrefillContinue,
  } = useForkPanel()

  // Fetch providers once on mount
  useEffect(() => {
    fetchProviders()
  }, [fetchProviders])

  if (!currentRhizome) return null

  // Compute which nodes are effectively excluded on the current path
  const effectiveExcludedIds = useMemo(() => {
    const pathNodeIds = new Set(path.map((n) => n.node_id))
    const excluded = new Set<string>()

    for (const ex of exclusions) {
      if (pathNodeIds.has(ex.scope_node_id)) {
        excluded.add(ex.node_id)
      }
    }

    for (const group of digressionGroups) {
      if (!group.included && group.node_ids.every((nid: string) => pathNodeIds.has(nid))) {
        for (const nid of group.node_ids) {
          excluded.add(nid)
        }
      }
    }

    return excluded
  }, [path, exclusions, digressionGroups])

  const handleExcludeToggle = useCallback((nodeId: string) => {
    if (!leafNodeId) return
    if (effectiveExcludedIds.has(nodeId)) {
      const pathNodeIds = new Set(path.map((n) => n.node_id))
      const matchingExclusion = exclusions.find(
        (ex) => ex.node_id === nodeId && pathNodeIds.has(ex.scope_node_id),
      )
      if (matchingExclusion) {
        includeNode(nodeId, matchingExclusion.scope_node_id)
      }
    } else {
      excludeNode(nodeId, leafNodeId)
    }
  }, [leafNodeId, effectiveExcludedIds, path, exclusions, excludeNode, includeNode])

  const handleSelectSibling = (parentId: string, siblingId: string) => {
    selectBranch(parentId, siblingId)
  }

  /**
   * Decide how to render each node based on its mode.
   * Completion-mode nodes → CompletionNode (heatmap primary, no markdown)
   * Everything else → MessageRow (standard chat rendering)
   */
  const isCompletionNode = (node: NodeResponse) =>
    node.mode === 'completion' || (node.role === 'assistant' && node.prompt_text != null)

  return (
    <div className="linear-view">
      <div className="messages">
        {path.map((node) => {
          const siblings = childMap.get(node.parent_id) ?? []
          const nodeParentKey = node.parent_id ?? ''

          if (isCompletionNode(node)) {
            return (
              <Fragment key={node.node_id}>
                <CompletionNode
                  node={node}
                  siblings={siblings}
                  actions={{
                    onSelectSibling: (siblingId) =>
                      handleSelectSibling(nodeParentKey, siblingId),
                    onFork: () => handleFork(nodeParentKey, node.role),
                    onGenerate: node.role === 'user' ? () => {
                      if (forkTarget?.parentId === node.node_id && forkTarget.mode === 'generate') {
                        setForkTarget(null)
                      } else {
                        setForkTarget({ parentId: node.node_id, mode: 'generate' })
                      }
                    } : undefined,
                    onBookmarkToggle: () => {
                      if (node.is_bookmarked) {
                        const bm = bookmarks.find((b) => b.node_id === node.node_id)
                        if (bm) removeBookmark(bm.bookmark_id)
                      } else {
                        addBookmark(node.node_id, node.content.slice(0, 60))
                      }
                    },
                    onExcludeToggle: () => handleExcludeToggle(node.node_id),
                    onAnchorToggle: () => toggleAnchor(node.node_id),
                    onSummarize: () => setSummarizeTargetId(
                      summarizeTargetId === node.node_id ? null : node.node_id
                    ),
                  }}
                  isExcludedOnPath={effectiveExcludedIds.has(node.node_id)}
                />
                {!isGenerating && forkTarget != null && (
                  forkTarget.mode === 'generate'
                    ? forkTarget.parentId === node.node_id
                    : forkTarget.parentId === nodeParentKey
                ) && (
                  <ForkPanel
                    mode={forkTarget.mode}
                    onForkSubmit={handleForkSubmit}
                    onRegenerateSubmit={handleRegenerateSubmit}
                    onPrefillSubmit={handlePrefillSubmit}
                    onPrefillContinue={handlePrefillContinue}
                    onCancel={() => setForkTarget(null)}
                    isGenerating={isGenerating}
                    providers={providers}
                    defaults={branchDefaults}
                    streamDefault={currentRhizome.metadata?.stream_responses !== false}
                    samplingDefaults={currentRhizome.default_sampling_params}
                  />
                )}
                {summarizeTargetId === node.node_id && (
                  <SummarizePanel
                    nodeId={node.node_id}
                    onClose={() => setSummarizeTargetId(null)}
                  />
                )}
              </Fragment>
            )
          }

          // Non-completion nodes: user messages, manual, prefill — render with MessageRow
          return (
            <Fragment key={node.node_id}>
              <MessageRow
                node={node}
                siblings={siblings}
                actions={{
                  onSelectSibling: (siblingId) =>
                    handleSelectSibling(nodeParentKey, siblingId),
                  onFork: () => handleFork(nodeParentKey, node.role),
                  onPrefill: node.role === 'user' ? () => {
                    if (forkTarget?.parentId === node.node_id && forkTarget.mode === 'prefill') {
                      setForkTarget(null)
                    } else {
                      setForkTarget({ parentId: node.node_id, mode: 'prefill' })
                    }
                  } : undefined,
                  onGenerate: node.role === 'user' ? () => {
                    if (forkTarget?.parentId === node.node_id && forkTarget.mode === 'generate') {
                      setForkTarget(null)
                    } else {
                      setForkTarget({ parentId: node.node_id, mode: 'generate' })
                    }
                  } : undefined,
                  onEdit: (nodeId, editedContent) => editNodeContent(nodeId, editedContent),
                  onInspect: node.role === 'assistant' && node.mode !== 'manual'
                    ? () => setInspectedNodeId(
                        inspectedNodeId === node.node_id ? null : node.node_id
                      )
                    : undefined,
                  onBookmarkToggle: () => {
                    if (node.is_bookmarked) {
                      const bm = bookmarks.find((b) => b.node_id === node.node_id)
                      if (bm) removeBookmark(bm.bookmark_id)
                    } else {
                      addBookmark(node.node_id, node.content.slice(0, 60))
                    }
                  },
                  onExcludeToggle: () => handleExcludeToggle(node.node_id),
                  onAnchorToggle: () => toggleAnchor(node.node_id),
                  onGroupToggle: () => {},
                  onSummarize: () => setSummarizeTargetId(
                    summarizeTargetId === node.node_id ? null : node.node_id
                  ),
                }}
                isExcludedOnPath={effectiveExcludedIds.has(node.node_id)}
              />
              {!isGenerating && forkTarget != null && (
                forkTarget.mode === 'prefill' || forkTarget.mode === 'generate'
                  ? forkTarget.parentId === node.node_id
                  : forkTarget.parentId === nodeParentKey
              ) && (
                <ForkPanel
                  mode={forkTarget.mode}
                  onForkSubmit={handleForkSubmit}
                  onRegenerateSubmit={handleRegenerateSubmit}
                  onPrefillSubmit={handlePrefillSubmit}
                  onPrefillContinue={handlePrefillContinue}
                  onCancel={() => setForkTarget(null)}
                  isGenerating={isGenerating}
                  providers={providers}
                  defaults={branchDefaults}
                  streamDefault={currentRhizome.metadata?.stream_responses !== false}
                  samplingDefaults={currentRhizome.default_sampling_params}
                />
              )}
              {summarizeTargetId === node.node_id && (
                <SummarizePanel
                  nodeId={node.node_id}
                  onClose={() => setSummarizeTargetId(null)}
                />
              )}
            </Fragment>
          )
        })}

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
            leafNodeId={leafNodeId}
            onRetry={regenerate}
            onChangeSettings={setForkTarget}
            onDismiss={clearGenerationError}
          />
        )}

        <div ref={bottomRef} />
      </div>

      {inspectedNodeId && (() => {
        const inspectedNode = nodes.find((n) => n.node_id === inspectedNodeId)
        if (!inspectedNode) return null
        return (
          <ContextModal
            context={reconstructContext(inspectedNode, nodes)}
            onDismiss={() => setInspectedNodeId(null)}
          />
        )
      })()}
    </div>
  )
}
