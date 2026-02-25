/**
 * Shared hooks extracted from LinearView for reuse by ChatView and CompletionView.
 * Stateful but not visual — these manage path computation, scroll behavior,
 * branch defaults, and fork panel state.
 */

import { type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { GenerateRequest, NodeResponse } from '../../api/types.ts'
import { getActivePath, useTreeStore, useTreeData, useStreamingState, useNavigation } from '../../store/treeStore.ts'

export interface ForkTarget {
  parentId: string
  mode: 'fork' | 'regenerate' | 'prefill' | 'generate'
}

/**
 * Compute the active path through the conversation tree, build sibling lookup,
 * and handle regeneration truncation.
 */
export function useActivePath() {
  const { currentTree } = useTreeData()
  const { branchSelections } = useNavigation()
  const { regeneratingParentId } = useStreamingState()

  const nodes = currentTree?.nodes ?? []
  let path = getActivePath(nodes, branchSelections)

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
  if (regeneratingParentId != null) {
    const cutIndex = path.findIndex((n) => n.parent_id === regeneratingParentId)
    if (cutIndex !== -1) {
      path = path.slice(0, cutIndex)
    }
  }

  const leafNodeId = path.length > 0 ? path[path.length - 1].node_id : null

  return { nodes, path, childMap, leafNodeId }
}

/**
 * Auto-scroll to bottom when the path grows (new messages) or streaming content arrives.
 */
export function useAutoScroll(bottomRef: RefObject<HTMLDivElement | null>) {
  const {
    streamingContent, streamingThinkingContent,
    streamingContents, activeStreamIndex,
  } = useStreamingState()
  const { currentTree } = useTreeData()
  const { branchSelections } = useNavigation()

  const nodes = currentTree?.nodes ?? []
  const path = getActivePath(nodes, branchSelections)
  const activeMultiContent = streamingContents[activeStreamIndex]

  const prevPathLenRef = useRef(path.length)
  useEffect(() => {
    const pathGrew = path.length > prevPathLenRef.current
    prevPathLenRef.current = path.length
    const hasStreamContent = !!streamingContent || !!streamingThinkingContent || !!activeMultiContent
    if (pathGrew || hasStreamContent) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [path.length, streamingContent, streamingThinkingContent, activeMultiContent, bottomRef])
}

/**
 * Watch for scrollToNodeId in the store (from search result navigation)
 * and scroll that DOM element into view.
 */
export function useScrollToNode() {
  const scrollToNodeId = useTreeStore(s => s.scrollToNodeId)
  const clearScrollToNode = useTreeStore(s => s.clearScrollToNode)

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
 * from the active path, falling back to tree defaults.
 */
export function useBranchDefaults(path: NodeResponse[]) {
  const { currentTree } = useTreeData()

  return useMemo(() => {
    const lastAssistant = [...path].reverse().find((n) => n.role === 'assistant')
    return {
      provider: lastAssistant?.provider ?? currentTree?.default_provider ?? '',
      model: lastAssistant?.model ?? currentTree?.default_model ?? '',
      systemPrompt: currentTree?.default_system_prompt ?? '',
    }
  }, [path, currentTree])
}

/**
 * Fork panel state and handlers — manages the forkTarget local state and
 * binds store actions for fork, regenerate, prefill, and generate operations.
 */
export function useForkPanel() {
  const [forkTarget, setForkTarget] = useState<ForkTarget | null>(null)

  const forkAndGenerate = useTreeStore(s => s.forkAndGenerate)
  const regenerate = useTreeStore(s => s.regenerate)
  const prefillAssistant = useTreeStore(s => s.prefillAssistant)
  const prefillAndGenerate = useTreeStore(s => s.prefillAndGenerate)

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
