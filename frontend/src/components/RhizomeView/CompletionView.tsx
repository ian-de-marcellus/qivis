/**
 * CompletionView — renders completion-mode rhizomes.
 *
 * Completion-mode replies render through CompletionNode (the heatmap is the
 * text); everything else -- user turns, manual and prefilled replies, chat
 * replies from other models -- through MessageRow. Shares its state, panels,
 * and footer with ChatView (useConversationView, ConversationParts); leaves
 * out the chat-only comparison, digression selection, and split view.
 */

import { Fragment, useEffect, useRef } from 'react'
import type { NodeResponse } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import { CompletionNode } from './CompletionNode.tsx'
import { ConversationEnd, InspectedContext, NodePanels } from './ConversationParts.tsx'
import { MessageRow } from './MessageRow.tsx'
import { useAutoScroll, useConversationView, useScrollToNode } from './useViewShared.ts'
import './ChatView.css'

const isCompletionNode = (node: NodeResponse) =>
  node.mode === 'completion' || (node.role === 'assistant' && node.prompt_text != null)

export function CompletionView() {
  const fetchProviders = useRhizomeStore(s => s.fetchProviders)
  const view = useConversationView()
  const { nodes, path, childMap, excludedIds } = view
  const bottomRef = useRef<HTMLDivElement>(null)
  useAutoScroll(bottomRef, path.length)
  useScrollToNode()

  useEffect(() => {
    fetchProviders()
  }, [fetchProviders])

  return (
    <div className="linear-view">
      <div className="messages">
        {path.map((node) => {
          const siblings = childMap.get(node.parent_id) ?? []
          const actions = view.actionsFor(node)
          return (
            <Fragment key={node.node_id}>
              {isCompletionNode(node) ? (
                <CompletionNode
                  node={node}
                  siblings={siblings}
                  actions={actions}
                  isExcludedOnPath={excludedIds.has(node.node_id)}
                />
              ) : (
                <MessageRow
                  node={node}
                  siblings={siblings}
                  actions={actions}
                  isExcludedOnPath={excludedIds.has(node.node_id)}
                />
              )}
              <NodePanels view={view} node={node} />
            </Fragment>
          )
        })}

        <ConversationEnd view={view} />
        <div ref={bottomRef} />
      </div>

      <InspectedContext nodes={nodes} />
    </div>
  )
}
