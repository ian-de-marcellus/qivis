/**
 * Steer a reply token by token, Dasher-style.
 *
 * The model's likeliest next tokens stream toward a crosshair as boxes as
 * tall as their probability. Point up or down to steer; how far right of the
 * line you point sets the speed (left of it backs up). Fly into a box and its
 * token is chosen; its own next tokens open up inside it. A token at or above
 * the auto-advance threshold flows through on its own and is recorded as the
 * model's choice; everything else is the researcher's.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { SteeringSession, TokenCandidate } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import { advance, type Box, boxAt, enter, exit, layout, screenY, tokenLabel, type View } from './dasherModel.ts'
import './SteerView.css'

const K = 20
const MAX_DEPTH = 3

interface Chosen {
  id: number
  token: string
  prob: number
  chosenBy: 'model' | 'researcher'
}

interface SteerViewProps {
  rhizomeId: string
  /** The node being answered (null: the model speaks first) */
  parentId: string | null
  provider: string
  model: string
  /** Other models that can be steered; choosing one starts over with it */
  modelOptions: string[]
  onModelChange: (model: string) => void
  onClose: () => void
}

const keyOf = (ids: number[]) => ids.join(',')

export function SteerView({
  rhizomeId, parentId, provider, model, modelOptions, onModelChange, onClose,
}: SteerViewProps) {
  const showNode = useRhizomeStore(s => s.showNode)

  const [session, setSession] = useState<SteeringSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tokens, setTokens] = useState<Chosen[]>([])
  const [paused, setPaused] = useState(true)
  const [cruise, setCruise] = useState(false)
  const [speed, setSpeed] = useState(1.2)
  const [threshold, setThreshold] = useState(0.99)
  const [ended, setEnded] = useState(false)
  const [typed, setTyped] = useState('')
  const [saving, setSaving] = useState(false)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  // Animation state lives in refs: the frame loop reads and writes it directly
  const live = useRef({
    view: { c: 0.5, s: 400 } as View,
    tokens: [] as Chosen[],
    cache: new Map<string, TokenCandidate[]>(),
    inflight: new Set<string>(),
    pointer: { x: 0, y: 0, inside: false },
    paused: true, cruise: false, speed: 1.2, threshold: 0.99, ended: false,
    stops: [] as string[],
    sessionId: null as string | null,
    // Columns: the current column's left edge on screen (eased), each depth's
    // label width from the last frame, and the widths of columns passed through
    colX: 0,
    colWidths: [] as number[],
    passed: [] as number[],
    height: 600,
  })
  useEffect(() => {
    Object.assign(live.current, { paused, cruise, speed, threshold, ended })
  }, [paused, cruise, speed, threshold, ended])

  // -- Session --

  useEffect(() => {
    let cancelled = false
    api.startSteering(rhizomeId, parentId, { provider, model })
      .then((s) => {
        if (cancelled) {
          api.steerDiscard(s.session_id).catch(() => {})
          return
        }
        live.current.sessionId = s.session_id
        live.current.stops = s.stop_sequences
        setSession(s)
      })
      .catch((e) => setError(String(e)))
    return () => {
      cancelled = true
    }
  }, [rhizomeId, parentId, provider, model])

  const fetchDist = useCallback((ids: number[]) => {
    const { cache, inflight, sessionId } = live.current
    const key = keyOf(ids)
    if (!sessionId || cache.has(key) || inflight.has(key)) return
    inflight.add(key)
    api.steerNext(sessionId, ids, K)
      .then((cands) => cache.set(key, cands))
      .catch((e) => setError(String(e)))
      .finally(() => inflight.delete(key))
  }, [])

  // -- Choosing and unchoosing --

  const publish = () => setTokens([...live.current.tokens])

  const choose = useCallback((box: Box, chosenBy: Chosen['chosenBy']) => {
    const L = live.current
    // The next column is already on screen, just right of this one: it stays put
    const width = L.colWidths[0] ?? 80
    L.passed.push(width)
    L.colX += width
    L.view = enter(L.view, box)
    // Taking a small box directly (keyboard, typing) starts the new column at rest
    if (L.view.s < L.height * 0.6) L.view = { c: 0.5, s: L.height * 0.9 }
    L.tokens.push({ id: box.id, token: box.token, prob: box.prob, chosenBy })
    if (L.stops.includes(box.token)) {
      L.ended = true
      setEnded(true)
      setPaused(true)
    }
    publish()
    fetchDist(L.tokens.map((t) => t.id))
  }, [fetchDist])

  const undo = useCallback(() => {
    const L = live.current
    const last = L.tokens.pop()
    if (!last) return
    const parent = L.cache.get(keyOf(L.tokens.map((t) => t.id)))
    const box = parent && layout(parent).find((b) => b.id === last.id)
    L.view = box ? exit(L.view, box) : { c: 0.5, s: L.view.s }
    L.colX -= L.passed.pop() ?? 80
    L.ended = false
    setEnded(false)
    publish()
  }, [])

  const chooseRank = useCallback((rank: number) => {
    const L = live.current
    if (L.ended) return
    const dist = L.cache.get(keyOf(L.tokens.map((t) => t.id)))
    const box = dist && layout(dist)[rank]
    if (box) choose(box, 'researcher')
  }, [choose])

  const appendTyped = async () => {
    const L = live.current
    if (!typed || !L.sessionId || L.ended) return
    try {
      const pieces = await api.steerTokenize(L.sessionId, typed)
      for (const piece of pieces) {
        const dist = L.cache.get(keyOf(L.tokens.map((t) => t.id)))
        const prob = dist?.find((c) => c.id === piece.id)?.prob ?? 0
        L.tokens.push({ id: piece.id, token: piece.token, prob, chosenBy: 'researcher' })
      }
      L.view = { c: 0.5, s: L.view.s }
      setTyped('')
      publish()
      fetchDist(L.tokens.map((t) => t.id))
    } catch (e) {
      setError(String(e))
    }
  }

  const keep = async () => {
    const L = live.current
    if (!L.sessionId || L.tokens.length === 0) return
    setSaving(true)
    try {
      const node = await api.steerCommit(
        L.sessionId, L.tokens.map((t) => t.id), L.tokens.map((t) => t.chosenBy),
      )
      L.sessionId = null
      await showNode(node.node_id)
      onClose()
    } catch (e) {
      setError(String(e))
      setSaving(false)
    }
  }

  const close = useCallback(() => {
    const id = live.current.sessionId
    if (id) api.steerDiscard(id).catch(() => {})
    onClose()
  }, [onClose])

  // -- Keyboard --

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') {
        if (e.key === 'Escape') (e.target as HTMLElement).blur()
        return
      }
      if (e.key === ' ') {
        e.preventDefault()
        setPaused((p) => !p)
      } else if (e.key === 'Backspace') {
        e.preventDefault()
        undo()
      } else if (e.key === 'Escape') {
        close()
      } else if (/^[1-9]$/.test(e.key) && live.current.paused) {
        chooseRank(Number(e.key) - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, close, chooseRank])

  // -- The frame loop --

  useEffect(() => {
    if (!session) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const L = live.current
    L.height = canvas.clientHeight
    L.view = { c: 0.5, s: canvas.clientHeight * 0.9 }
    L.colX = canvas.clientWidth
    fetchDist([])

    let frame = 0
    let last = performance.now()
    const loop = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      const W = canvas.clientWidth
      const H = canvas.clientHeight
      L.height = H
      const dpr = window.devicePixelRatio || 1
      if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
        canvas.width = Math.round(W * dpr)
        canvas.height = Math.round(H * dpr)
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const crossX = W * 0.18
      const crossY = H / 2
      // An option is passed into when it's grown this tall; its column meets the line then
      const enterH = H * 0.72

      const ids = L.tokens.map((t) => t.id)
      const dist = L.cache.get(keyOf(ids))
      if (!dist) fetchDist(ids)
      const boxes = dist ? layout(dist) : []

      if (!L.paused && !L.ended && dist) {
        // A near-certain token flows through on its own: the model's choice
        const top = boxes[0]
        if (top && top.prob >= L.threshold && !L.stops.includes(top.token)) {
          choose(top, 'model')
        } else if (L.pointer.inside) {
          const targetY = L.view.c + (L.pointer.y - crossY) / L.view.s
          const reach = Math.max(-1, Math.min(1, (L.pointer.x - crossX) / (W - crossX)))
          const rate = L.cruise ? (L.pointer.x < crossX ? -L.speed : L.speed) : L.speed * 2 * reach
          L.view = advance(L.view, { targetY, rate, dt })

          const under = boxAt(boxes, L.view.c)
          if (under && (under.b - under.a) * L.view.s >= enterH) {
            choose(under, 'researcher')
          } else if (L.view.s < H * 0.45) {
            if (L.tokens.length > 0) undo()
            else L.view = { ...L.view, s: H * 0.45 }
          }
        }
      }

      // The column slides toward the line as the option under the crosshair grows
      const focus = dist ? boxAt(layout(dist), L.view.c) : undefined
      const grown = focus ? Math.min(1, ((focus.b - focus.a) * L.view.s) / enterH) : 0
      const restX = crossX + (W - crossX) * 0.22
      const targetX = restX + (crossX - restX) * grown
      L.colX += (targetX - L.colX) * Math.min(1, 8 * dt)

      draw(ctx, W, H, crossX, crossY, focus?.id)
      frame = requestAnimationFrame(loop)
    }

    const draw = (
      g: CanvasRenderingContext2D, W: number, H: number, crossX: number, crossY: number,
      focusId?: number,
    ) => {
      const css = getComputedStyle(canvas)
      const color = (name: string) => css.getPropertyValue(name).trim() || '#888'
      g.fillStyle = color('--bg-primary')
      g.fillRect(0, 0, W, H)

      const ids = L.tokens.map((t) => t.id)
      const dist = L.cache.get(keyOf(ids))
      const top = screenY(L.view, 0, crossY)
      const x0 = L.colX
      if (!dist) {
        g.fillStyle = color('--text-tertiary')
        g.font = `14px ${color('--font-ui')}`
        g.fillText('Asking the model…', Math.max(x0, crossX) + 16, crossY)
      } else {
        const column = layout(dist)
        const listed = column.length ? column[column.length - 1].b : 0
        // Probability not among the listed tokens: reachable only by typing
        const restTop = top + listed * L.view.s
        const restH = (1 - listed) * L.view.s
        if (restH > 1 && restTop < H) {
          g.fillStyle = color('--bg-secondary')
          g.fillRect(x0, restTop, W - x0, restH)
          if (restH > 16) {
            g.fillStyle = color('--text-tertiary')
            g.font = `11px ${color('--font-ui')}`
            g.fillText('other tokens (type to choose)', x0 + 8, restTop + 14)
          }
        }
        const widths: number[] = []
        drawColumn(g, column, ids, top, L.view.s, 0, x0, W, H, color, widths, focusId)
        L.colWidths = widths
      }

      // The crosshair
      g.strokeStyle = color('--accent')
      g.lineWidth = 1.5
      g.beginPath()
      g.moveTo(crossX, 0)
      g.lineTo(crossX, H)
      g.moveTo(crossX - 8, crossY)
      g.lineTo(crossX + 8, crossY)
      g.stroke()
      if (L.pointer.inside && !L.paused) {
        g.fillStyle = color('--accent')
        g.beginPath()
        g.arc(L.pointer.x, L.pointer.y, 3, 0, Math.PI * 2)
        g.fill()
      }
    }

    // One column of options, all starting at x so their labels line up; each
    // option's own next tokens form the column to its right, inside it.
    const drawColumn = (
      g: CanvasRenderingContext2D, column: Box[], prefix: number[], top: number, height: number,
      depth: number, x: number, W: number, H: number, color: (n: string) => string,
      widths: number[], focusId?: number,
    ) => {
      if (x >= W - 8) return
      const crossY = H / 2
      const childX = x + (L.colWidths[depth] ?? 80)
      for (const box of column) {
        const y = top + box.a * height
        const h = (box.b - box.a) * height
        if (y > H || y + h < 0 || h < 0.5) continue
        const isStop = L.stops.includes(box.token)
        const focused = depth === 0 && box.id === focusId
        g.fillStyle = isStop
          ? color('--ctx-red')
          : focused ? color('--bg-selected')
            : (box.rank + depth) % 2 === 0 ? color('--bg-secondary') : color('--bg-hover')
        g.globalAlpha = isStop ? 0.35 : 1
        g.fillRect(x, y, W - x, h)
        g.globalAlpha = 1
        g.strokeStyle = color('--border-subtle')
        g.lineWidth = 1
        g.strokeRect(x + 0.5, y + 0.5, W - x - 1, h - 1)

        if (h > 11) {
          const size = Math.max(10, Math.min(26, h * 0.32))
          g.font = `${size}px ${color('--font-mono')}`
          g.textBaseline = 'middle'
          const label = isStop ? 'end of turn' : tokenLabel(box.token)
          // Keep the label on screen, and level with the crosshair when the box spans it
          const labelY = h > 60
            ? Math.max(Math.max(y, 0) + size, Math.min(Math.min(y + h, H) - size, crossY))
            : y + h / 2
          g.fillStyle = focused ? color('--text-accent') : color('--text-primary')
          g.fillText(label, x + 8, labelY, Math.max(20, W - x - 16))
          let used = g.measureText(label).width
          if (h > 34) {
            g.fillStyle = color('--text-tertiary')
            g.font = `11px ${color('--font-ui')}`
            const pct = `${(box.prob * 100).toFixed(box.prob < 0.01 ? 2 : 0)}%`
            g.fillText(pct, x + 8, labelY + size * 0.85)
            used = Math.max(used, g.measureText(pct).width)
          }
          widths[depth] = Math.max(widths[depth] ?? 56, used + 24)
          g.textBaseline = 'alphabetic'
        }

        // What could come next after this option: the next column, inside it
        if (depth < MAX_DEPTH && !isStop && h > 60) {
          const childIds = [...prefix, box.id]
          const children = L.cache.get(keyOf(childIds))
          if (!children) fetchDist(childIds)
          else drawColumn(g, layout(children), childIds, y, h, depth + 1, childX, W, H, color, widths)
        }
      }
    }

    frame = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(frame)
  }, [session, choose, undo, fetchDist])

  const onPointer = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    Object.assign(live.current.pointer, { x: e.clientX - rect.left, y: e.clientY - rect.top, inside: true })
  }

  const context = session?.prompt_text ?? ''

  return (
    <div className="steer-overlay" role="dialog" aria-label="Steer a reply">
      <div className="steer-panel">
        <div className="steer-side">
          <div className="steer-title">
            <span>Steer</span>
            <select
              className="steer-model"
              value={model}
              onChange={(e) => onModelChange(e.target.value)}
              title="Choosing another model starts over"
            >
              {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          <div className="steer-label">Context (end)</div>
          <pre className="steer-context">{context.slice(-600)}</pre>

          <div className="steer-label">
            Reply
            <span className="steer-legend">
              <span className="steer-by-researcher">steered</span> ·{' '}
              <span className="steer-by-model">flowed through</span>
            </span>
          </div>
          <div className="steer-text">
            {tokens.map((t, i) => (
              <span
                key={i}
                className={t.chosenBy === 'model' ? 'steer-by-model' : 'steer-by-researcher'}
                title={`${(t.prob * 100).toFixed(2)}% · ${t.chosenBy === 'model' ? 'flowed through' : 'steered'}`}
              >
                {session?.stop_sequences.includes(t.token) ? ' [end of turn]' : t.token}
              </span>
            ))}
            {!ended && <span className="steer-caret" />}
          </div>

          <div className="steer-type">
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') appendTyped() }}
              placeholder="Type text to add as your choice…"
              disabled={!session || ended}
            />
          </div>

          <div className="steer-controls">
            <button onClick={() => setPaused((p) => !p)} disabled={!session || ended}>
              {paused ? 'Go' : 'Pause'}
            </button>
            <button onClick={undo} disabled={tokens.length === 0}>Undo</button>
            <button onClick={() => setCruise((c) => !c)} className={cruise ? 'active' : ''}>
              {cruise ? 'Cruise' : 'Pointer speed'}
            </button>
          </div>

          <label className="steer-slider">
            <span>Speed</span>
            <input type="range" min={0.3} max={3} step={0.1} value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))} />
          </label>
          <label className="steer-slider">
            <span>Flow through at {threshold >= 1 ? 'never' : `${Math.round(threshold * 1000) / 10}%`}</span>
            <input type="range" min={0.9} max={1} step={0.005} value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))} />
          </label>

          <p className="steer-help">
            Space: go/pause · point up/down to steer, further right to go faster, left of the
            line to back up · Backspace: undo · 1–9 (paused): take a ranked token · Esc: close
          </p>

          {error && <div className="steer-error">{error}</div>}

          <div className="steer-actions">
            <button className="steer-discard" onClick={close}>Discard</button>
            <button className="steer-keep" onClick={keep} disabled={saving || tokens.length === 0}>
              {saving ? 'Saving…' : ended ? 'Keep reply' : 'Keep so far'}
            </button>
          </div>
        </div>

        <canvas
          ref={canvasRef}
          className="steer-canvas"
          onPointerMove={onPointer}
          onPointerEnter={onPointer}
          onPointerLeave={() => { live.current.pointer.inside = false }}
          onClick={() => setPaused((p) => !p)}
        />
      </div>
    </div>
  )
}
