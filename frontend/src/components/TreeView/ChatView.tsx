import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTreeStore, useTreeData, useStreamingState, useComparison, useDigressionState, useResearchMetadata } from '../../store/treeStore.ts'
import { ComparisonView } from '../ComparisonView/ComparisonView.tsx'
import { ComparisonPickerBanner } from './ComparisonPickerBanner.tsx'
import { ContextModal } from './ContextModal.tsx'
import { ContextSplitView } from './ContextSplitView.tsx'
import { reconstructContext } from './contextReconstruction.ts'
import {
  computeDiffSummary,
  buildComparisonRows,
  buildOriginalContext,
  getPathToNode,
  getTreeDefaults,
} from './contextDiffs.ts'
import type { DiffSummary } from './contextDiffs.ts'
import { DigressionCreator } from './DigressionPanel.tsx'
import { ForkPanel } from './ForkPanel.tsx'
import { GenerationErrorPanel } from './GenerationErrorPanel.tsx'
import { MessageRow } from './MessageRow.tsx'
import { StreamingDisplay } from './StreamingDisplay.tsx'
import { SummarizePanel } from './SummarizePanel.tsx'
import { useActivePath, useAutoScroll, useScrollToNode, useBranchDefaults, useForkPanel } from './useViewShared.ts'
import './DigressionPanel.css'
import './ChatView.css'

export function ChatView() {
  const { currentTree, providers } = useTreeData()
  const {
    isGenerating, streamingContent, streamingThinkingContent,
    streamingContents, streamingThinkingContents, streamingNodeIds,
    streamingTotal, activeStreamIndex, generationError,
    stopGeneration,
  } = useStreamingState()
  const {
    splitViewNodeId, comparisonNodeId, comparisonPickingMode,
    comparisonPickingSourceId, inspectedNodeId,
  } = useComparison()
  const { digressionGroups, groupSelectionMode, selectedGroupNodeIds } = useDigressionState()
  const { bookmarks, exclusions, selectedEditVersion, editHistoryCache } = useResearchMetadata()

  const selectBranch = useTreeStore(s => s.selectBranch)
  const editNodeContent = useTreeStore(s => s.editNodeContent)
  const setActiveStreamIndex = useTreeStore(s => s.setActiveStreamIndex)
  const regenerate = useTreeStore(s => s.regenerate)
  const clearGenerationError = useTreeStore(s => s.clearGenerationError)
  const fetchProviders = useTreeStore(s => s.fetchProviders)
  const setInspectedNodeId = useTreeStore(s => s.setInspectedNodeId)
  const setSplitViewNodeId = useTreeStore(s => s.setSplitViewNodeId)
  const addBookmark = useTreeStore(s => s.addBookmark)
  const removeBookmark = useTreeStore(s => s.removeBookmark)
  const excludeNode = useTreeStore(s => s.excludeNode)
  const includeNode = useTreeStore(s => s.includeNode)
  const toggleAnchor = useTreeStore(s => s.toggleAnchor)
  const setGroupSelectionMode = useTreeStore(s => s.setGroupSelectionMode)
  const toggleGroupNodeSelection = useTreeStore(s => s.toggleGroupNodeSelection)
  const createDigressionGroup = useTreeStore(s => s.createDigressionGroup)
  const setComparisonNodeId = useTreeStore(s => s.setComparisonNodeId)
  const enterComparisonPicking = useTreeStore(s => s.enterComparisonPicking)
  const pickComparisonTarget = useTreeStore(s => s.pickComparisonTarget)
  const cancelComparisonPicking = useTreeStore(s => s.cancelComparisonPicking)

  const bottomRef = useRef<HTMLDivElement>(null)
  const [comparingAtParent, setComparingAtParent] = useState<string | null>(null)
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

  // Esc key cancels comparison picking mode
  useEffect(() => {
    if (!comparisonPickingMode) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        cancelComparisonPicking()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [comparisonPickingMode, cancelComparisonPicking])

  if (!currentTree) return null

  // Compute highlight classes when an edit version is selected
  const highlights = useMemo(() => {
    const map = new Map<string, 'highlight-used' | 'highlight-other'>()
    if (!selectedEditVersion) return map

    const { nodeId, entry } = selectedEditVersion
    const editedNodeIdx = path.findIndex((n) => n.node_id === nodeId)
    if (editedNodeIdx === -1) return map

    // Determine the time window for this version
    const cachedEntries = editHistoryCache[nodeId]
    if (!cachedEntries && entry !== null) return map // history not loaded yet for non-original

    const editedNode = path[editedNodeIdx]

    let windowStart: string
    let windowEnd: string | null = null

    if (entry === null) {
      // "Original" pseudo-entry — active from node creation until first edit
      windowStart = editedNode.created_at
      if (cachedEntries && cachedEntries.length > 0) {
        windowEnd = cachedEntries[0].timestamp
      }
    } else {
      // Specific edit entry — find its position in the ordered list
      windowStart = entry.timestamp
      if (cachedEntries) {
        const entryIdx = cachedEntries.findIndex((e) => e.event_id === entry.event_id)
        if (entryIdx !== -1 && entryIdx < cachedEntries.length - 1) {
          windowEnd = cachedEntries[entryIdx + 1].timestamp
        }
      }
    }

    // Walk all assistant nodes after the edited node in the path
    for (let i = editedNodeIdx + 1; i < path.length; i++) {
      const n = path[i]
      if (n.role !== 'assistant') continue

      const nodeTime = n.created_at
      const inWindow = nodeTime >= windowStart && (windowEnd === null || nodeTime < windowEnd)
      map.set(n.node_id, inWindow ? 'highlight-used' : 'highlight-other')
    }

    return map
  }, [selectedEditVersion, path, editHistoryCache])

  // Compute diff summaries for assistant nodes (for diff badges)
  const diffSummaries = useMemo(() => {
    const map = new Map<string, DiffSummary>()
    if (!currentTree) return map
    const treeDefaults = getTreeDefaults(currentTree)
    for (const node of path) {
      if (node.role === 'assistant' && node.mode !== 'manual') {
        map.set(node.node_id, computeDiffSummary(node, path, treeDefaults))
      }
    }
    return map
  }, [currentTree, path])

  // Compute which nodes are effectively excluded on the current path
  const effectiveExcludedIds = useMemo(() => {
    const pathNodeIds = new Set(path.map((n) => n.node_id))
    const excluded = new Set<string>()

    // Node-level exclusions: apply if scope_node_id is on the current path
    for (const ex of exclusions) {
      if (pathNodeIds.has(ex.scope_node_id)) {
        excluded.add(ex.node_id)
      }
    }

    // Group-level exclusions: if group is toggled off and all its nodes are on the path
    for (const group of digressionGroups) {
      if (!group.included && group.node_ids.every((nid) => pathNodeIds.has(nid))) {
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
      // Find the exclusion record that applies on this path to remove it
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

  const handleGroupNodeToggle = useCallback((nodeId: string) => {
    toggleGroupNodeSelection(nodeId)
  }, [toggleGroupNodeSelection])

  const handleCreateGroup = useCallback(async (label: string) => {
    if (selectedGroupNodeIds.length < 2) return
    // Order by path position
    const pathOrder = path.map((n) => n.node_id)
    const ordered = [...selectedGroupNodeIds].sort(
      (a, b) => pathOrder.indexOf(a) - pathOrder.indexOf(b),
    )
    const ok = await createDigressionGroup({ node_ids: ordered, label })
    if (ok) setGroupSelectionMode(false)
  }, [selectedGroupNodeIds, path, createDigressionGroup, setGroupSelectionMode])

  const handleSelectSibling = (parentId: string, siblingId: string) => {
    selectBranch(parentId, siblingId)
  }

  // In picking mode, determine which nodes are pickable (non-manual assistant nodes, excluding source)
  const pickableNodeIds = useMemo(() => {
    if (!comparisonPickingMode) return null
    const set = new Set<string>()
    for (const node of path) {
      if (node.role === 'assistant' && node.mode !== 'manual' && node.node_id !== comparisonPickingSourceId) {
        set.add(node.node_id)
      }
    }
    return set
  }, [comparisonPickingMode, path, comparisonPickingSourceId])

  // Find the source node for the picker banner
  const pickingSourceNode = comparisonPickingMode && comparisonPickingSourceId
    ? nodes.find((n) => n.node_id === comparisonPickingSourceId) ?? null
    : null

  return (
    <div className="linear-view">
      <div className="messages">
        {comparisonPickingMode && pickingSourceNode && (
          <ComparisonPickerBanner
            sourceModel={pickingSourceNode.model}
            sourceTimestamp={pickingSourceNode.created_at}
            sourceResponsePreview={pickingSourceNode.content.slice(0, 200)}
            onCancel={cancelComparisonPicking}
          />
        )}

        {!comparisonPickingMode && groupSelectionMode && (
          <DigressionCreator
            selectedNodeIds={selectedGroupNodeIds}
            onToggleNode={handleGroupNodeToggle}
            onCancel={() => setGroupSelectionMode(false)}
            onCreate={handleCreateGroup}
          />
        )}

        {path.map((node) => {
          const siblings = childMap.get(node.parent_id) ?? []
          const nodeParentKey = node.parent_id ?? ''
          const isPicking = comparisonPickingMode
          const isPickable = pickableNodeIds?.has(node.node_id) ?? false

          return (
            <Fragment key={node.node_id}>
              <MessageRow
                node={node}
                siblings={siblings}
                actions={{
                  onSelectSibling: (siblingId) =>
                    handleSelectSibling(nodeParentKey, siblingId),
                  onFork: isPicking ? () => {} : () => handleFork(nodeParentKey, node.role),
                  onPrefill: isPicking ? undefined : node.role === 'user' ? () => {
                    if (forkTarget?.parentId === node.node_id && forkTarget.mode === 'prefill') {
                      setForkTarget(null)
                    } else {
                      setForkTarget({ parentId: node.node_id, mode: 'prefill' })
                    }
                  } : undefined,
                  onGenerate: isPicking ? undefined : node.role === 'user' ? () => {
                    if (forkTarget?.parentId === node.node_id && forkTarget.mode === 'generate') {
                      setForkTarget(null)
                    } else {
                      setForkTarget({ parentId: node.node_id, mode: 'generate' })
                    }
                  } : undefined,
                  onEdit: isPicking ? undefined : (nodeId, editedContent) => editNodeContent(nodeId, editedContent),
                  onInspect: isPicking ? undefined : node.role === 'assistant' && node.mode !== 'manual'
                    ? () => setInspectedNodeId(
                        inspectedNodeId === node.node_id ? null : node.node_id
                      )
                    : undefined,
                  onSplitView: isPicking ? undefined : diffSummaries.has(node.node_id)
                    ? () => setSplitViewNodeId(
                        splitViewNodeId === node.node_id ? null : node.node_id
                      )
                    : undefined,
                  onBookmarkToggle: isPicking ? undefined : () => {
                    if (node.is_bookmarked) {
                      const bm = bookmarks.find((b) => b.node_id === node.node_id)
                      if (bm) removeBookmark(bm.bookmark_id)
                    } else {
                      addBookmark(node.node_id, node.content.slice(0, 60))
                    }
                  },
                  onExcludeToggle: isPicking ? undefined : () => handleExcludeToggle(node.node_id),
                  onAnchorToggle: isPicking ? undefined : () => toggleAnchor(node.node_id),
                  onGroupToggle: () => handleGroupNodeToggle(node.node_id),
                  onCompare: isPicking ? undefined : siblings.length > 1 ? () => setComparingAtParent(
                    comparingAtParent === nodeParentKey ? null : nodeParentKey,
                  ) : undefined,
                  onComparisonPick: isPicking && isPickable ? () => pickComparisonTarget(node.node_id) : undefined,
                  onSummarize: isPicking ? undefined : () => setSummarizeTargetId(
                    summarizeTargetId === node.node_id ? null : node.node_id
                  ),
                }}
                isExcludedOnPath={effectiveExcludedIds.has(node.node_id)}
                groupSelectable={!isPicking && groupSelectionMode}
                groupSelected={selectedGroupNodeIds.includes(node.node_id)}
                diffSummary={isPicking ? undefined : diffSummaries.get(node.node_id)}
                highlightClass={highlights.get(node.node_id)}
                comparisonPickable={isPicking ? isPickable : undefined}
              />
              {!isPicking && comparingAtParent === nodeParentKey && (
                <ComparisonView
                  siblings={siblings}
                  selectedNodeId={node.node_id}
                  onSelect={(selectedId) => {
                    selectBranch(nodeParentKey, selectedId)
                    setComparingAtParent(null)
                  }}
                  onDismiss={() => setComparingAtParent(null)}
                />
              )}
              {!isPicking && !isGenerating && forkTarget != null && (
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
                  streamDefault={currentTree.metadata?.stream_responses !== false}
                  samplingDefaults={currentTree.default_sampling_params}
                />
              )}
              {!isPicking && summarizeTargetId === node.node_id && (
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

      {splitViewNodeId && currentTree && (() => {
        const splitNode = nodes.find((n) => n.node_id === splitViewNodeId)
        if (!splitNode) return null
        const treeDefaults = getTreeDefaults(currentTree)

        const contextB = reconstructContext(splitNode, nodes)
        const pathB = getPathToNode(splitNode, nodes)

        let contextA
        let responseContentA: string | null = null
        let comparisonMode: 'original' | 'node' = 'original'

        // Guard: if comparisonNodeId === splitViewNodeId, fall back to Original
        const effectiveComparisonId = comparisonNodeId !== splitViewNodeId ? comparisonNodeId : null
        const compNode = effectiveComparisonId
          ? nodes.find((n) => n.node_id === effectiveComparisonId) ?? null
          : null

        if (compNode) {
          contextA = reconstructContext(compNode, nodes)
          responseContentA = compNode.content
          comparisonMode = 'node'
        } else {
          contextA = buildOriginalContext(splitNode, nodes, treeDefaults)
        }

        const pathA = compNode ? getPathToNode(compNode, nodes) : pathB
        const comparisonRows = buildComparisonRows(contextA, contextB, pathA, pathB)

        return (
          <ContextSplitView
            rows={comparisonRows}
            summary={comparisonMode === 'original' ? computeDiffSummary(splitNode, path, treeDefaults) : null}
            contextA={contextA}
            contextB={contextB}
            responseContentA={responseContentA}
            responseContentB={splitNode.content}
            comparisonMode={comparisonMode}
            onDismiss={() => setSplitViewNodeId(null)}
            onCompareToOther={enterComparisonPicking}
            onCompareToOriginal={() => setComparisonNodeId(null)}
          />
        )
      })()}
    </div>
  )
}
