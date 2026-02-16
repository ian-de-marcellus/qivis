/**
 * Word-level diff using Longest Common Subsequence.
 * Compares a base string against another, producing segments
 * marked as common, added (in other but not base), or removed
 * (in base but not other).
 */

export interface DiffSegment {
  text: string
  type: 'common' | 'added' | 'removed'
}

/** Split on whitespace boundaries, keeping whitespace attached to the following word. */
function tokenize(text: string): string[] {
  const tokens: string[] = []
  const re = /\S+/g
  let match: RegExpExecArray | null
  let lastEnd = 0

  while ((match = re.exec(text)) !== null) {
    // Include leading whitespace with this word
    const start = match.index
    const prefix = text.slice(lastEnd, start)
    tokens.push(prefix + match[0])
    lastEnd = re.lastIndex
  }

  // Trailing whitespace (rare, but handle it)
  if (lastEnd < text.length) {
    if (tokens.length > 0) {
      tokens[tokens.length - 1] += text.slice(lastEnd)
    } else {
      tokens.push(text.slice(lastEnd))
    }
  }

  return tokens
}

/** Strip leading whitespace for comparison — we compare word content, not spacing. */
function wordContent(token: string): string {
  return token.trimStart()
}

/** Compute LCS length table. */
function lcsTable(a: string[], b: string[]): number[][] {
  const m = a.length
  const n = b.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (wordContent(a[i - 1]) === wordContent(b[j - 1])) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  return dp
}

/** Backtrack through the LCS table to produce diff segments. */
function backtrack(
  dp: number[][],
  baseTokens: string[],
  otherTokens: string[],
): DiffSegment[] {
  const segments: DiffSegment[] = []
  let i = baseTokens.length
  let j = otherTokens.length

  // Build segments in reverse, then flip
  const raw: DiffSegment[] = []

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && wordContent(baseTokens[i - 1]) === wordContent(otherTokens[j - 1])) {
      raw.push({ text: otherTokens[j - 1], type: 'common' })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      raw.push({ text: otherTokens[j - 1], type: 'added' })
      j--
    } else {
      raw.push({ text: baseTokens[i - 1], type: 'removed' })
      i--
    }
  }

  raw.reverse()

  // Merge adjacent segments of the same type
  for (const seg of raw) {
    const last = segments[segments.length - 1]
    if (last && last.type === seg.type) {
      last.text += seg.text
    } else {
      segments.push({ ...seg })
    }
  }

  return segments
}

/**
 * Compute word-level diff between base and other text.
 * Returns segments from the perspective of `other` relative to `base`:
 * - 'common': text present in both
 * - 'added': text in other but not in base
 * - 'removed': text in base but not in other
 */
export function computeWordDiff(base: string, other: string): DiffSegment[] {
  if (base === other) return [{ text: other, type: 'common' }]
  if (!base) return [{ text: other, type: 'added' }]
  if (!other) return [{ text: base, type: 'removed' }]

  const baseTokens = tokenize(base)
  const otherTokens = tokenize(other)

  const dp = lcsTable(baseTokens, otherTokens)
  return backtrack(dp, baseTokens, otherTokens)
}
