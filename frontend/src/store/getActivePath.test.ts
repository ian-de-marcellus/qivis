import { describe, expect, it } from 'vitest'
import type { NodeResponse } from '../api/types.ts'
import { getActivePath } from './rhizomeStore.ts'

const node = (node_id: string, parent_id: string | null) => ({ node_id, parent_id }) as NodeResponse
//   a ─ b ─ c
//     └ d        (d is newer than b)
const NODES = [node('a', null), node('b', 'a'), node('c', 'b'), node('d', 'a')]
const ids = (path: NodeResponse[]) => path.map((n) => n.node_id)

describe('getActivePath', () => {
  it('follows the newest child by default', () => {
    expect(ids(getActivePath(NODES, {}))).toEqual(['a', 'd'])
  })

  it('follows a selected branch, keyed by parent ("" for roots)', () => {
    expect(ids(getActivePath(NODES, { a: 'b' }))).toEqual(['a', 'b', 'c'])
    const twoRoots = [...NODES, node('r', null)]
    expect(ids(getActivePath(twoRoots, { '': 'a', a: 'b' }))).toEqual(['a', 'b', 'c'])
  })

  it('falls back to the newest when a selection is stale', () => {
    expect(ids(getActivePath(NODES, { a: 'gone' }))).toEqual(['a', 'd'])
  })

  it('is empty for an empty rhizome', () => {
    expect(getActivePath([], {})).toEqual([])
  })
})
