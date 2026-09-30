/**
 * Names never to shortlist, whatever a model makes of them today: taken as
 * references by AI products (future pretraining will know them), or ruled out
 * for any other reason. One list for every study and discovery.
 */

import { useEffect, useState } from 'react'
import * as api from '../../api/client.ts'

export function ExcludedNames({ onChange }: { onChange: (names: string[]) => void }) {
  const [text, setText] = useState('')
  const [saved, setSaved] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getExcludedNames().then(({ names }) => {
      setSaved(names)
      setText(names.join(', '))
      onChange(names)
    }).catch((e) => setError(String(e)))
  }, [onChange])

  const parse = (t: string) => [...new Set(t.split(/[,\n]/).map((n) => n.trim()).filter(Boolean))]
  const dirty = parse(text).join('|') !== saved.join('|')

  const save = async () => {
    try {
      const { names } = await api.setExcludedNames(parse(text))
      setSaved(names)
      onChange(names)
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div className="new-study">
      <p className="hint">
        Names never to shortlist, in any study or discovery: taken by AI products (future pretraining will
        know them as references, whatever a model makes of them today), or ruled out for any other reason.
        Case matters: "ELIZA" and "Eliza" are different names.
      </p>
      <label className="field">
        <span>Excluded names (comma or line separated)</span>
        <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      {error && <div className="study-error">{error}</div>}
      <div className="run-row">
        <button className="run" onClick={save} disabled={!dirty}>Save</button>
        <span className="hint">{saved.length} excluded</span>
      </div>
    </div>
  )
}
