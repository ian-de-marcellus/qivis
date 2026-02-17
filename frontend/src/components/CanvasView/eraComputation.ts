/**
 * Era computation for the 2D Canvas View.
 *
 * Takes the active path + intervention timeline and computes a 2D grid
 * where vertical = messages, horizontal = eras (temporal epochs between
 * interventions).
 */

import type { InterventionEntry, NodeResponse } from '../../api/types.ts'
import type { TreeDefaults } from '../TreeView/contextDiffs.ts'

// -- Types --

export interface EraCell {
  type: 'normal' | 'edited' | 'absent' | 'system-prompt'
  nodeId: string | null           // null for system-prompt cells
  role: string | null
  content: string                 // The content as it existed in this era
  isChanged: boolean              // Different from the last era that had content here?
}

export interface Era {
  index: number
  label: string                   // "Original", "Edit 1", "Edit 2", etc.
  timestamp: string | null        // When this era began (null for era 0)
  intervention: InterventionEntry | null  // The triggering intervention (null for era 0)
  cells: EraCell[]                // One per row, aligned with rowLabels
  lastActiveRow: number           // Index of the last row with real content
}

export interface CanvasGrid {
  rowLabels: RowLabel[]           // One per message in the path + system prompt row
  eras: Era[]
}

export interface RowLabel {
  nodeId: string | null           // null for system-prompt row
  role: string
  index: number                   // Position in the conversation (0 = system prompt)
}

// -- Algorithm --

/**
 * Compute lastActiveRow for an era: the index of the last path node
 * whose created_at is before the given cutoff timestamp.
 * If cutoff is null (last era), includes all rows.
 */
function computeLastActiveRow(
  pathNodes: NodeResponse[],
  totalRows: number,
  cutoffTimestamp: string | null,
): number {
  if (cutoffTimestamp == null) return totalRows - 1

  let last = 0 // system prompt row at minimum
  for (let rowIdx = 1; rowIdx < totalRows; rowIdx++) {
    const node = pathNodes[rowIdx - 1]
    if (node.created_at < cutoffTimestamp) {
      last = rowIdx
    }
  }
  return last
}

/**
 * Compute the 2D canvas grid from a path, intervention timeline, and tree defaults.
 *
 * Row 0 = system prompt. Rows 1..N = path nodes.
 * Era 0 = original state. Eras 1..M = one per intervention.
 */
export function computeCanvasGrid(
  pathNodes: NodeResponse[],
  interventions: InterventionEntry[],
  treeDefaults: TreeDefaults,
): CanvasGrid {
  // Build row labels: system prompt row + one per path node
  const rowLabels: RowLabel[] = [
    { nodeId: null, role: 'system', index: 0 },
    ...pathNodes.map((node, i) => ({
      nodeId: node.node_id,
      role: node.role,
      index: i + 1,
    })),
  ]

  const totalRows = rowLabels.length

  // Cumulative edit state: nodeId -> edited content
  const editMap = new Map<string, string>()
  // Track system prompt separately
  let currentSystemPrompt = treeDefaults.default_system_prompt ?? ''

  // Era 0's lastActiveRow: messages that existed before the first intervention
  // (or all messages if no interventions)
  const era0Cutoff = interventions.length > 0 ? interventions[0].timestamp : null
  const era0LastActiveRow = computeLastActiveRow(pathNodes, totalRows, era0Cutoff)

  // Era 0: original state (no edits applied)
  const era0Cells: EraCell[] = []

  // System prompt cell — always present in era 0
  era0Cells.push({
    type: 'system-prompt',
    nodeId: null,
    role: 'system',
    content: treeDefaults.default_system_prompt ?? '',
    isChanged: true, // First appearance — always show content
  })

  // Path node cells
  for (let i = 0; i < pathNodes.length; i++) {
    const node = pathNodes[i]
    const rowIdx = i + 1

    if (rowIdx > era0LastActiveRow) {
      // This message didn't exist yet in the original era
      era0Cells.push({
        type: 'absent',
        nodeId: node.node_id,
        role: node.role,
        content: '',
        isChanged: false,
      })
    } else {
      era0Cells.push({
        type: node.mode === 'manual' ? 'edited' : 'normal',
        nodeId: node.node_id,
        role: node.role,
        content: node.content,
        isChanged: true, // First appearance — always show content
      })
    }
  }

  const eras: Era[] = [{
    index: 0,
    label: 'Original',
    timestamp: null,
    intervention: null,
    cells: era0Cells,
    lastActiveRow: era0LastActiveRow,
  }]

  // Track the last known content for each row.
  // null = row has never appeared (first appearance will be isChanged: true).
  // Only updated for non-absent cells, so absent gaps don't poison later comparisons.
  const lastKnownContent: (string | null)[] = new Array(totalRows).fill(null)
  for (let i = 0; i < era0Cells.length; i++) {
    if (era0Cells[i].type !== 'absent') {
      lastKnownContent[i] = era0Cells[i].content
    }
  }

  // Process each intervention as a new era
  for (let iIdx = 0; iIdx < interventions.length; iIdx++) {
    const intervention = interventions[iIdx]

    // Apply intervention to cumulative state
    if (intervention.intervention_type === 'node_edited' && intervention.node_id) {
      if (intervention.new_content != null) {
        editMap.set(intervention.node_id, intervention.new_content)
      } else {
        // Restore to original
        editMap.delete(intervention.node_id)
      }
    } else if (intervention.intervention_type === 'system_prompt_changed') {
      currentSystemPrompt = (intervention.new_value as string) ?? ''
    }

    // Compute lastActiveRow: nodes created before the NEXT intervention (or all if last)
    const nextTimestamp = iIdx < interventions.length - 1
      ? interventions[iIdx + 1].timestamp
      : null
    let lastActiveRow = computeLastActiveRow(pathNodes, totalRows, nextTimestamp)

    // If nothing qualifies beyond system prompt, use previous era's extent
    if (lastActiveRow === 0 && eras.length > 0) {
      lastActiveRow = eras[eras.length - 1].lastActiveRow
    }

    // Build cells for this era
    const cells: EraCell[] = []

    // System prompt cell
    const sysContent = currentSystemPrompt
    const sysChanged = lastKnownContent[0] === null || sysContent !== lastKnownContent[0]
    cells.push({
      type: 'system-prompt',
      nodeId: null,
      role: 'system',
      content: sysContent,
      isChanged: sysChanged,
    })
    lastKnownContent[0] = sysContent

    // Path node cells
    for (let rowIdx = 1; rowIdx < totalRows; rowIdx++) {
      const node = pathNodes[rowIdx - 1]

      if (rowIdx > lastActiveRow) {
        // This message didn't exist yet in this era
        cells.push({
          type: 'absent',
          nodeId: node.node_id,
          role: node.role,
          content: '',
          isChanged: false,
        })
        // Do NOT update lastKnownContent — absent doesn't count
        continue
      }

      // Compute content: use edit map if available, else original
      const editedContent = editMap.get(node.node_id)
      const content = editedContent ?? node.content
      const wasEdited = editedContent != null

      // Compare against last known content (skipping absent eras)
      const isChanged = lastKnownContent[rowIdx] === null || content !== lastKnownContent[rowIdx]

      cells.push({
        type: wasEdited ? 'edited' : 'normal',
        nodeId: node.node_id,
        role: node.role,
        content,
        isChanged,
      })
      lastKnownContent[rowIdx] = content
    }

    eras.push({
      index: iIdx + 1,
      label: `Edit ${iIdx + 1}`,
      timestamp: intervention.timestamp,
      intervention,
      cells,
      lastActiveRow,
    })
  }

  return { rowLabels, eras }
}
