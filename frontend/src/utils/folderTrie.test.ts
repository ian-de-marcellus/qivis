import { describe, expect, it } from 'vitest'
import type { RhizomeSummary } from '../api/types.ts'
import { buildFolderTrie, collectRhizomeIds, findFolderNode } from './folderTrie.ts'

const rhizome = (rhizome_id: string, folders: string[]) => ({ rhizome_id, folders }) as RhizomeSummary

describe('folderTrie', () => {
  const trie = buildFolderTrie(
    [rhizome('1', ['Research/Sun']), rhizome('2', ['Research']), rhizome('3', ['Research/Sun', 'Guests'])],
    ['Empty/Later'],
  )

  it('builds nested folders from slash paths, including ghost folders', () => {
    expect(trie.map((f) => f.name).sort()).toEqual(['Empty', 'Guests', 'Research'])
    expect(findFolderNode(trie, 'Research/Sun')?.rhizomeIds).toEqual(['1', '3'])
    expect(findFolderNode(trie, 'Empty/Later')?.rhizomeIds).toEqual([])
  })

  it('collects rhizomes from a folder and everything under it', () => {
    expect(collectRhizomeIds(findFolderNode(trie, 'Research')!).sort()).toEqual(['1', '2', '3'])
  })
})
