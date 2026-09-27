import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRhizomeStore, useRhizomeData, useComparison, useDigressionState, useResearchMetadata } from '../../store/rhizomeStore.ts'
import { ComparisonView } from '../ComparisonView/ComparisonView.tsx'
import { ComparisonPickerBanner } from './ComparisonPickerBanner.tsx'
import { ContextSplitView } from './ContextSplitView.tsx'
import { ConversationEnd, InspectedContext, NodePanels } from './ConversationParts.tsx'
import { reconstructContext } from './contextReconstruction.ts'
import {
  computeDiffSummary,
  buildComparisonRows,
  buildOriginalContext,
  getPathToNode,
  getRhizomeDefaults,
} from './contextDiffs.ts'
import type { DiffSummary } from './contextDiffs.ts'
import { DigressionCreator } from './DigressionPanel.tsx'
import { MessageRow } from './MessageRow.tsx'
import { useAutoScroll, useConversationView, useScrollToNode } from './useViewShared.ts'
import './DigressionPanel.css'
import './ChatView.css'

export function ChatView() {
  const { currentRhizome } = useRhizomeData()
  const {
    splitViewNodeId, comparisonNodeId, comparisonPickingMode, comparisonPickingSourceId,
  } = useComparison()
  const { groupSelectionMode, selectedGroupNodeIds } = useDigressionState()
  const { selectedEditVersion, editHistoryCache } = useResearchMetadata()

  const selectBranch = useRhizomeStore(s => s.selectBranch)
  const fetchProviders = useRhizomeStore(s => s.fetchProviders)
  const setSplitViewNodeId = useRhizomeStore(s => s.setSplitViewNodeId)
  const setGroupSelectionMode = useRhizomeStore(s => s.setGroupSelectionMode)
  const toggleGroupNodeSelection = useRhizomeStore(s => s.toggleGroupNodeSelection)
  const createDigressionGroup = useRhizomeStore(s => s.createDigressionGroup)
  const setComparisonNodeId = useRhizomeStore(s => s.setComparisonNodeId)
  const enterComparisonPicking = useRhizomeStore(s => s.enterComparisonPicking)
  const pickComparisonTarget = useRhizomeStore(s => s.pickComparisonTarget)
  const cancelComparisonPicking = useRhizomeStore(s => s.cancelComparisonPicking)

  const view = useConversationView()
  const { nodes, path, childMap, excludedIds } = view
  const bottomRef = useRef<HTMLDivElement>(null)
  const [comparingAtParent, setComparingAtParent] = useState<string | null>(null)
  useAutoScroll(bottomRef, path.length)
  useScrollToNode()

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
    if (!currentRhizome) return map
    const rhizomeDefaults = getRhizomeDefaults(currentRhizome)
    for (const node of path) {
      if (node.role === 'assistant' && node.mode !== 'manual') {
        map.set(node.node_id, computeDiffSummary(node, path, rhizomeDefaults))
      }
    }
    return map
  }, [currentRhizome, path])

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

  if (!currentRhizome) return null

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
            onToggleNode={toggleGroupNodeSelection}
            onCancel={() => setGroupSelectionMode(false)}
            onCreate={handleCreateGroup}
          />
        )}

        {path.map((node) => {
          const siblings = childMap.get(node.parent_id) ?? []
          const nodeParentKey = node.parent_id ?? ''
          const isPicking = comparisonPickingMode
          const isPickable = pickableNodeIds?.has(node.node_id) ?? false

          // While picking a comparison target, rows only offer "pick this one"
          const actions = isPicking
            ? {
                onSelectSibling: (siblingId: string) => selectBranch(nodeParentKey, siblingId),
                onFork: () => {},
                onGroupToggle: () => toggleGroupNodeSelection(node.node_id),
                onComparisonPick: isPickable ? () => pickComparisonTarget(node.node_id) : undefined,
              }
            : {
                ...view.actionsFor(node),
                onSplitView: diffSummaries.has(node.node_id)
                  ? () => setSplitViewNodeId(splitViewNodeId === node.node_id ? null : node.node_id)
                  : undefined,
                onCompare: siblings.length > 1
                  ? () => setComparingAtParent(comparingAtParent === nodeParentKey ? null : nodeParentKey)
                  : undefined,
              }

          return (
            <Fragment key={node.node_id}>
              <MessageRow
                node={node}
                siblings={siblings}
                actions={actions}
                isExcludedOnPath={excludedIds.has(node.node_id)}
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
              {!isPicking && <NodePanels view={view} node={node} />}
            </Fragment>
          )
        })}

        <ConversationEnd view={view} showFirstTurn={!comparisonPickingMode} />
        <div ref={bottomRef} />
      </div>

      <InspectedContext nodes={nodes} />
      {splitViewNodeId && currentRhizome && (() => {
        const splitNode = nodes.find((n) => n.node_id === splitViewNodeId)
        if (!splitNode) return null
        const rhizomeDefaults = getRhizomeDefaults(currentRhizome)

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
          contextA = buildOriginalContext(splitNode, nodes, rhizomeDefaults)
        }

        const pathA = compNode ? getPathToNode(compNode, nodes) : pathB
        const comparisonRows = buildComparisonRows(contextA, contextB, pathA, pathB)

        return (
          <ContextSplitView
            rows={comparisonRows}
            summary={comparisonMode === 'original' ? computeDiffSummary(splitNode, path, rhizomeDefaults) : null}
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
