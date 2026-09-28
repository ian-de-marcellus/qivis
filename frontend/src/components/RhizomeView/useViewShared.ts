/**
 * Shared hooks extracted from LinearView for reuse by ChatView and CompletionView.
 * Stateful but not visual — these manage path computation, scroll behavior,
 * branch defaults, and fork panel state.
 */

import { type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { GenerateRequest, NodeResponse } from '../../api/types.ts'
import { getActivePath, useRhizomeStore, useRhizomeData, useStreamingState, useNavigation } from '../../store/rhizomeStore.ts'

export interface ForkTarget {
  parentId: string
  mode: 'fork' | 'regenerate' | 'prefill' | 'generate'
}

/**
 * Compute the active path through the conversation rhizome, build sibling lookup,
 * and handle regeneration truncation.
 */
export function useActivePath() {
  const { currentRhizome } = useRhizomeData()
  const { branchSelections } = useNavigation()
  const { regeneratingParentId } = useStreamingState()

  const nodes = useMemo(() => currentRhizome?.nodes ?? [], [currentRhizome])
  const fullPath = useMemo(() => getActivePath(nodes, branchSelections), [nodes, branchSelections])

  // Build childMap for sibling lookups
  const childMap = useMemo(() => {
    const map = new Map<string | null, NodeResponse[]>()
    for (const node of nodes) {
      const children = map.get(node.parent_id) ?? []
      children.push(node)
      map.set(node.parent_id, children)
    }
    return map
  }, [nodes])

  // When regenerating, truncate the path at the regeneration point
  // so the old assistant message (and everything below it) disappears
  const path = useMemo(() => {
    if (regeneratingParentId == null) return fullPath
    // '' is the root key: regenerating a root node truncates the whole path
    const cutIndex = fullPath.findIndex((n) => (n.parent_id ?? '') === regeneratingParentId)
    return cutIndex === -1 ? fullPath : fullPath.slice(0, cutIndex)
  }, [fullPath, regeneratingParentId])

  const leafNodeId = path.length > 0 ? path[path.length - 1].node_id : null

  return { nodes, path, childMap, leafNodeId }
}

/**
 * Keep the newest content in view: scroll to the bottom when the path grows
 * (a message was added), and follow streaming text -- unless the reader has
 * scrolled up to read something, in which case leave them there.
 */
export function useAutoScroll(bottomRef: RefObject<HTMLDivElement | null>, pathLength: number) {
  const {
    streamingContent, streamingThinkingContent,
    streamingContents, activeStreamIndex,
  } = useStreamingState()
  const activeMultiContent = streamingContents[activeStreamIndex]

  const prevPathLenRef = useRef(pathLength)
  useEffect(() => {
    const pathGrew = pathLength > prevPathLenRef.current
    prevPathLenRef.current = pathLength
    const streaming = !!streamingContent || !!streamingThinkingContent || !!activeMultiContent
    if (pathGrew || (streaming && isNearBottom(bottomRef.current))) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [pathLength, streamingContent, streamingThinkingContent, activeMultiContent, bottomRef])
}

function isNearBottom(el: HTMLElement | null): boolean {
  let scroller = el?.parentElement ?? null
  while (scroller && scroller.scrollHeight <= scroller.clientHeight) scroller = scroller.parentElement
  if (!scroller) return true
  return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160
}

/**
 * Watch for scrollToNodeId in the store (from search result navigation)
 * and scroll that DOM element into view.
 */
export function useScrollToNode() {
  const scrollToNodeId = useRhizomeStore(s => s.scrollToNodeId)
  const clearScrollToNode = useRhizomeStore(s => s.clearScrollToNode)

  useEffect(() => {
    if (!scrollToNodeId) return
    // Defer to next frame so the DOM has updated with the new path
    requestAnimationFrame(() => {
      const el = document.querySelector(`[data-node-id="${scrollToNodeId}"]`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
      clearScrollToNode()
    })
  }, [scrollToNodeId, clearScrollToNode])
}

/**
 * Compute branch-local defaults: use the last assistant node's provider/model
 * from the active path, falling back to rhizome defaults.
 */
export function useBranchDefaults(path: NodeResponse[]) {
  const { currentRhizome } = useRhizomeData()

  return useMemo(() => {
    const lastAssistant = [...path].reverse().find((n) => n.role === 'assistant')
    return {
      provider: lastAssistant?.provider ?? currentRhizome?.default_provider ?? '',
      model: lastAssistant?.model ?? currentRhizome?.default_model ?? '',
      systemPrompt: currentRhizome?.default_system_prompt ?? '',
      mode: (lastAssistant?.mode === 'chat' || lastAssistant?.mode === 'completion'
        ? lastAssistant.mode
        : undefined) as 'chat' | 'completion' | undefined,
    }
  }, [path, currentRhizome])
}

/**
 * Fork panel state and handlers — manages the forkTarget local state and
 * binds store actions for fork, regenerate, prefill, and generate operations.
 */
export function useForkPanel() {
  const [forkTarget, setForkTarget] = useState<ForkTarget | null>(null)

  const forkAndGenerate = useRhizomeStore(s => s.forkAndGenerate)
  const regenerate = useRhizomeStore(s => s.regenerate)
  const prefillAssistant = useRhizomeStore(s => s.prefillAssistant)
  const prefillAndGenerate = useRhizomeStore(s => s.prefillAndGenerate)

  const handleFork = useCallback((parentId: string, role: string) => {
    const mode = role === 'assistant' ? 'regenerate' : 'fork'
    if (forkTarget?.parentId === parentId && forkTarget.mode === mode) {
      setForkTarget(null)
    } else {
      setForkTarget({ parentId, mode })
    }
  }, [forkTarget])

  const handleForkSubmit = useCallback((content: string, overrides: GenerateRequest) => {
    if (forkTarget != null) {
      forkAndGenerate(forkTarget.parentId, content, overrides)
      setForkTarget(null)
    }
  }, [forkTarget, forkAndGenerate])

  const handleRegenerateSubmit = useCallback((overrides: GenerateRequest) => {
    if (forkTarget != null) {
      regenerate(forkTarget.parentId, overrides)
      setForkTarget(null)
    }
  }, [forkTarget, regenerate])

  const handlePrefillSubmit = useCallback((content: string) => {
    if (forkTarget != null) {
      prefillAssistant(forkTarget.parentId, content)
      setForkTarget(null)
    }
  }, [forkTarget, prefillAssistant])

  const handlePrefillContinue = useCallback((content: string, overrides: GenerateRequest) => {
    if (forkTarget != null) {
      prefillAndGenerate(forkTarget.parentId, content, overrides)
      setForkTarget(null)
    }
  }, [forkTarget, prefillAndGenerate])

  return {
    forkTarget,
    setForkTarget,
    handleFork,
    handleForkSubmit,
    handleRegenerateSubmit,
    handlePrefillSubmit,
    handlePrefillContinue,
  }
}

export type NodePanelKind = 'summarize' | 'replay' | 'crossModel' | 'writeResponse' | 'probe'

/**
 * Everything a conversation view (chat or completion) shares: the active
 * path, the fork panel, which per-node panel is open, which nodes are
 * excluded on this path, and the actions every node row offers.
 */
export function useConversationView() {
  const active = useActivePath()
  const { path, leafNodeId } = active
  const fork = useForkPanel()
  const branchDefaults = useBranchDefaults(path)
  const { forkTarget, setForkTarget, handleFork } = fork

  const [openPanel, setOpenPanel] = useState<{ kind: NodePanelKind; nodeId: string } | null>(null)
  const togglePanel = useCallback((kind: NodePanelKind, nodeId: string) => {
    setOpenPanel((open) => (open?.kind === kind && open.nodeId === nodeId ? null : { kind, nodeId }))
  }, [])
  const closePanel = useCallback(() => setOpenPanel(null), [])

  const exclusions = useRhizomeStore(s => s.exclusions)
  const digressionGroups = useRhizomeStore(s => s.digressionGroups)
  const bookmarks = useRhizomeStore(s => s.bookmarks)
  const inspectedNodeId = useRhizomeStore(s => s.inspectedNodeId)
  const selectBranch = useRhizomeStore(s => s.selectBranch)
  const editNodeContent = useRhizomeStore(s => s.editNodeContent)
  const setInspectedNodeId = useRhizomeStore(s => s.setInspectedNodeId)
  const addBookmark = useRhizomeStore(s => s.addBookmark)
  const removeBookmark = useRhizomeStore(s => s.removeBookmark)
  const excludeNode = useRhizomeStore(s => s.excludeNode)
  const includeNode = useRhizomeStore(s => s.includeNode)
  const toggleAnchor = useRhizomeStore(s => s.toggleAnchor)
  const toggleGroupNodeSelection = useRhizomeStore(s => s.toggleGroupNodeSelection)
  const openSteer = useRhizomeStore(s => s.openSteer)

  // Nodes excluded on this path: by a node exclusion scoped to a node on the
  // path, or by a switched-off digression group lying wholly on the path
  const excludedIds = useMemo(() => {
    const onPath = new Set(path.map((n) => n.node_id))
    const excluded = new Set<string>()
    for (const ex of exclusions) {
      if (onPath.has(ex.scope_node_id)) excluded.add(ex.node_id)
    }
    for (const group of digressionGroups) {
      if (!group.included && group.node_ids.every((nid) => onPath.has(nid))) {
        for (const nid of group.node_ids) excluded.add(nid)
      }
    }
    return excluded
  }, [path, exclusions, digressionGroups])

  const toggleExclude = useCallback((nodeId: string) => {
    if (!leafNodeId) return
    if (!excludedIds.has(nodeId)) {
      excludeNode(nodeId, leafNodeId)
      return
    }
    const onPath = new Set(path.map((n) => n.node_id))
    const applying = exclusions.find((ex) => ex.node_id === nodeId && onPath.has(ex.scope_node_id))
    if (applying) includeNode(nodeId, applying.scope_node_id)
  }, [leafNodeId, excludedIds, path, exclusions, excludeNode, includeNode])

  const toggleForkTarget = useCallback((nodeId: string, mode: 'prefill' | 'generate') => {
    setForkTarget(forkTarget?.parentId === nodeId && forkTarget.mode === mode ? null : { parentId: nodeId, mode })
  }, [forkTarget, setForkTarget])

  /** The actions every node row offers, in either view. */
  const actionsFor = (node: NodeResponse) => {
    const parentKey = node.parent_id ?? ''
    const isUser = node.role === 'user'
    return {
      onSelectSibling: (siblingId: string) => selectBranch(parentKey, siblingId),
      onFork: () => handleFork(parentKey, node.role),
      onPrefill: isUser ? () => toggleForkTarget(node.node_id, 'prefill') : undefined,
      onGenerate: isUser ? () => toggleForkTarget(node.node_id, 'generate') : undefined,
      onEdit: (nodeId: string, editedContent: string | null) => editNodeContent(nodeId, editedContent),
      onInspect: node.role === 'assistant' && node.mode !== 'manual'
        ? () => setInspectedNodeId(inspectedNodeId === node.node_id ? null : node.node_id)
        : undefined,
      onBookmarkToggle: () => {
        if (!node.is_bookmarked) {
          addBookmark(node.node_id, node.content.slice(0, 60))
          return
        }
        const bm = bookmarks.find((b) => b.node_id === node.node_id)
        if (bm) removeBookmark(bm.bookmark_id)
      },
      onExcludeToggle: () => toggleExclude(node.node_id),
      onAnchorToggle: () => toggleAnchor(node.node_id),
      onGroupToggle: () => toggleGroupNodeSelection(node.node_id),
      onSummarize: () => togglePanel('summarize', node.node_id),
      onReplay: () => togglePanel('replay', node.node_id),
      onCrossModel: () => togglePanel('crossModel', node.node_id),
      onWriteResponse: isUser ? () => togglePanel('writeResponse', node.node_id) : undefined,
      onSteer: () => openSteer(node.node_id),
      onProbe: () => togglePanel('probe', node.node_id),
    }
  }

  return {
    ...active,
    fork,
    branchDefaults,
    openPanel,
    closePanel,
    excludedIds,
    actionsFor,
  }
}
