import { useRef, useState } from 'react'
import { useClickOutside } from '../../hooks/useClickOutside.ts'
import { useEscapeKey } from '../../hooks/useEscapeKey.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import './AppSettings.css'

/** App-wide display preferences (not per rhizome), remembered across reloads. */
export function AppSettings() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const showNodeIds = useRhizomeStore(s => s.showNodeIds)
  useClickOutside(ref, open, () => setOpen(false))
  useEscapeKey(open, () => setOpen(false))

  const setShowNodeIds = (v: boolean) => {
    useRhizomeStore.setState({ showNodeIds: v })
    try { localStorage.setItem('qivis-show-node-ids', v ? '1' : '0') } catch { /* private mode */ }
  }

  return (
    <div className="app-settings" ref={ref}>
      <button
        className="theme-toggle"
        onClick={() => setOpen(!open)}
        aria-label="App settings"
        aria-expanded={open}
        title="App settings"
      >
        &#9881;
      </button>
      {open && (
        <div className="app-settings-popover" role="dialog" aria-label="App settings">
          <div className="app-settings-title">Display</div>
          <label className="app-settings-row">
            <input
              type="checkbox"
              checked={showNodeIds}
              onChange={(e) => setShowNodeIds(e.target.checked)}
            />
            Show node IDs on messages
          </label>
        </div>
      )}
    </div>
  )
}
