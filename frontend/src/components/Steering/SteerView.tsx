/**
 * Steer a reply token by token, Dasher-style.
 *
 * The model's likeliest next tokens stand in a column, each as tall as its
 * probability, with the tokens that could follow each one in the column to
 * its right. Moving forward carries the column toward the line while the
 * option you're pointing at grows to fill the screen; reach the line and it's
 * chosen, and the next column is already in place. Every token takes the same
 * travel, so a certain token is just one big box you pass through; likelihood
 * shows as size (easy or hard to stay on), not speed. Point left of the line
 * to back up. Every token in a steered reply is the researcher's choice.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { SteeringSession, TokenCandidate } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import {
  advance, type Box, boxAt, enter, exit, layout, screenY, throttle, tokenLabel, type View,
  wordsOnly, zones,
} from './dasherModel.ts'
import './SteerView.css'

const K = 20
/** A column at rest fills this much of the canvas height */
const REST = 0.9
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
  /** Its role: after one of the model's own turns, it's the researcher's turn first */
  parentRole: string | null
  provider: string
  model: string
  /** Other models that can be steered; choosing one starts over with it */
  modelOptions: string[]
  onModelChange: (model: string) => void
  onClose: () => void
}

const keyOf = (ids: number[]) => ids.join(',')

/** The options as shown: all of them, or words only (renormalized, the turn's end kept) */
const shown = (L: { words: boolean; stops: string[] }, dist: TokenCandidate[]) =>
  (L.words ? wordsOnly(dist, L.stops) : dist)

/** The reply has reached its end of turn: a stop token (chat templates), or
 *  text ending in a stop string (a transcript's next speaker line). */
function reachedEnd(tokens: { token: string }[], stops: string[]): boolean {
  const last = tokens[tokens.length - 1]?.token
  if (last && stops.includes(last)) return true
  const text = tokens.map((t) => t.token).join('')
  return stops.some((stop) => stop.length > 0 && text.endsWith(stop))
}

export function SteerView({
  rhizomeId, parentId, parentRole, provider, model, modelOptions, onModelChange, onClose,
}: SteerViewProps) {
  const showNode = useRhizomeStore(s => s.showNode)
  const openSteer = useRhizomeStore(s => s.openSteer)

  const [session, setSession] = useState<SteeringSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tokens, setTokens] = useState<Chosen[]>([])
  const [paused, setPaused] = useState(true)
  const [cruise, setCruise] = useState(false)
  const [speed, setSpeed] = useState(1.2)
  const [ended, setEnded] = useState(false)
  const [typed, setTyped] = useState('')
  const [saving, setSaving] = useState(false)
  // Steer through end of turn into the model's version of the next turn (user sim)
  const [pastEnd, setPastEnd] = useState(false)
  // Hide numbers and symbols: options given the next token is a word
  const [words, setWords] = useState(false)
  // The reply ended and was kept: the researcher writes the next turn
  const [yourTurn, setYourTurn] = useState<string | null>(null)
  const [myMessage, setMyMessage] = useState('')
  // Opened on the model's turn (nothing kept this time), vs arriving at end of turn
  const [turnFromOpen, setTurnFromOpen] = useState(false)

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const finishTurn = useRef<() => void>(() => {})
  // Animation state lives in refs: the frame loop reads and writes it directly
  const live = useRef({
    view: { c: 0.5, s: 400 } as View,
    tokens: [] as Chosen[],
    cache: new Map<string, TokenCandidate[]>(),
    inflight: new Set<string>(),
    // Distributions that failed: not asked again (every frame) until Retry
    failed: new Set<string>(),
    pointer: { x: 0, y: 0, inside: false },
    // Where each drawn option is on screen, with the path of options to it (deepest last)
    hits: [] as { x: number; y: number; h: number; path: Box[] }[],
    paused: true, cruise: false, speed: 1.2, ended: false, pastEnd: false, words: false,
    // How far the current column has traveled toward the line, 0..1
    progress: 0,
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
    Object.assign(live.current, { paused, cruise, speed, ended, pastEnd, words })
  }, [paused, cruise, speed, ended, pastEnd, words])

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
        // A conversation with turns that ends on the model's: the researcher speaks next
        // (a base model's plain continuation has no turns, so it just keeps steering)
        if (parentId && parentRole === 'assistant' && s.stop_sequences.length > 0) {
          setYourTurn(parentId)
          setTurnFromOpen(true)
        }
      })
      .catch((e) => setError(String(e)))
    return () => {
      cancelled = true
    }
  }, [rhizomeId, parentId, parentRole, provider, model])

  // Unkept sessions end with the view (the server would expire them anyway)
  useEffect(() => () => {
    const id = live.current.sessionId
    if (id) api.steerDiscard(id).catch(() => {})
  }, [])

  const fetchDist = useCallback((ids: number[]) => {
    const L = live.current
    const { cache, inflight, failed, sessionId } = L
    const key = keyOf(ids)
    // A finished turn is being (or has been) kept, which closes its session
    if (!sessionId || L.ended) return
    if (cache.has(key) || inflight.has(key) || failed.has(key)) return
    inflight.add(key)
    api.steerNext(sessionId, ids, K)
      .then((cands) => cache.set(key, cands))
      .catch((e) => {
        failed.add(key)
        // Only this session's troubles matter, and only while it's still open
        if (L.sessionId === sessionId && !L.ended) setError(String(e))
      })
      .finally(() => inflight.delete(key))
  }, [])

  // -- Choosing and unchoosing --

  const publish = () => setTokens([...live.current.tokens])

  const choose = useCallback((box: Box, chosenBy: Chosen['chosenBy']) => {
    const L = live.current
    // The next column is already on screen, just right of this one: it stays put
    L.passed.push(L.colWidths[0] ?? 80)
    L.view = enter(L.view, box)
    // Arriving by travel, the box already fills the screen; taken directly
    // (keyboard, typing), start the new column at rest
    if (L.progress < 0.99) L.view = { c: 0.5, s: L.height * REST }
    L.progress = 0
    L.tokens.push({ id: box.id, token: box.token, prob: box.prob, chosenBy })
    if (reachedEnd(L.tokens, L.stops) && !L.pastEnd) {
      L.ended = true
      setEnded(true)
      setPaused(true)
      queueMicrotask(() => finishTurn.current())
    }
    publish()
    fetchDist(L.tokens.map((t) => t.id))
  }, [fetchDist])

  const undo = useCallback(() => {
    const L = live.current
    const last = L.tokens.pop()
    if (!last) return
    L.passed.pop()
    const parent = L.cache.get(keyOf(L.tokens.map((t) => t.id)))
    const box = parent && layout(shown(L, parent)).find((b) => b.id === last.id)
    // Back out to where we arrived from: the parent column at the line, this box filling the screen
    L.view = box ? exit({ c: 0.5, s: L.height * REST }, box) : { c: 0.5, s: L.height * REST }
    L.progress = box ? 0.999 : 0
    L.ended = false
    setEnded(false)
    publish()
  }, [])

  const chooseRank = useCallback((rank: number) => {
    const L = live.current
    if (L.ended) return
    const dist = L.cache.get(keyOf(L.tokens.map((t) => t.id)))
    const box = dist && layout(shown(L, dist))[rank]
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
        if (reachedEnd(L.tokens, L.stops) && !L.pastEnd) {
          L.ended = true
          setEnded(true)
          setPaused(true)
          queueMicrotask(() => finishTurn.current())
          break
        }
      }
      L.view = { c: 0.5, s: L.view.s }
      setTyped('')
      publish()
      fetchDist(L.tokens.map((t) => t.id))
    } catch (e) {
      setError(String(e))
    }
  }

  const keep = useCallback(async ({ thenYourTurn }: { thenYourTurn: boolean }) => {
    const L = live.current
    if (!L.sessionId || L.tokens.length === 0) return
    setSaving(true)
    try {
      const node = await api.steerCommit(
        L.sessionId, L.tokens.map((t) => t.id), L.tokens.map((t) => t.chosenBy),
      )
      L.sessionId = null
      await showNode(node.node_id)
      if (thenYourTurn) {
        setSaving(false)
        setYourTurn(node.node_id)
      } else {
        onClose()
      }
    } catch (e) {
      setError(String(e))
      setSaving(false)
    }
  }, [showNode, onClose])

  // Ending the turn yourself: the reply is kept as it stands (recorded as
  // ended by the researcher, not with end-of-turn tokens the model never
  // chose), and the conversation comes back to you
  const endTurn = useCallback(() => {
    const L = live.current
    if (L.ended || L.tokens.length === 0 || !L.sessionId) return
    L.ended = true
    setEnded(true)
    setPaused(true)
    void keep({ thenYourTurn: true })
  }, [keep])

  // Reaching end of turn keeps the reply and hands the conversation back
  // (choose() runs in the frame loop, so it reaches keep through a ref)
  useEffect(() => {
    finishTurn.current = () => void keep({ thenYourTurn: true })
  }, [keep])

  const sendMyTurn = async () => {
    if (!yourTurn || !myMessage.trim()) return
    try {
      const mine = await api.createNode(rhizomeId, {
        content: myMessage.trim(), role: 'user', parent_id: yourTurn,
      })
      await showNode(mine.node_id)
      openSteer(mine.node_id) // a fresh session steering her reply to it
    } catch (e) {
      setError(String(e))
    }
  }

  const close = useCallback(() => {
    const id = live.current.sessionId
    if (id) api.steerDiscard(id).catch(() => {})
    onClose()
  }, [onClose])

  // Leaving with steered tokens not yet kept asks once (click or Esc again to confirm)
  const [confirmClose, setConfirmClose] = useState(false)
  const requestClose = useCallback(() => {
    const unkept = live.current.sessionId != null && live.current.tokens.length > 0
    if (unkept && !confirmClose) setConfirmClose(true)
    else close()
  }, [close, confirmClose])

  // -- Keyboard --

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') {
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
        requestClose()
      } else if (e.key === 'Enter' && tag !== 'BUTTON') {
        e.preventDefault()
        endTurn()
      } else if (/^[1-9]$/.test(e.key) && live.current.paused) {
        chooseRank(Number(e.key) - 1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, requestClose, chooseRank, endTurn])

  // -- The frame loop --

  useEffect(() => {
    if (!session) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const L = live.current
    L.height = canvas.clientHeight
    L.view = { c: 0.5, s: canvas.clientHeight * REST }
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

      const ids = L.tokens.map((t) => t.id)
      const dist = L.cache.get(keyOf(ids))
      if (!dist) fetchDist(ids)
      const boxes = dist ? layout(shown(L, dist)) : []

      const restH = H * REST
      // Steering stays within the listed options (the rest is reachable by typing)
      const listed = boxes.length ? boxes[boxes.length - 1].b : 1
      if (L.view.c >= listed) L.view = { ...L.view, c: listed - 1e-6 }
      const focus = boxAt(boxes, L.view.c)
      if (!L.paused && !L.ended && dist && focus && L.pointer.inside) {
        // Travel: steady, a column per 1/speed seconds at full throttle
        const dir = L.cruise ? (L.pointer.x < crossX ? -1 : 1) : throttle(L.pointer.x, crossX, W)
        L.progress += dir * L.speed * 0.8 * dt

        // Steer toward the pointer; near the line, settle onto the option there
        const pointerY = L.view.c + (L.pointer.y - crossY) / L.view.s
        const settle = Math.max(0, (L.progress - 0.6) / 0.4) ** 2
        const targetC = pointerY + ((focus.a + focus.b) / 2 - pointerY) * settle
        L.view = advance(L.view, { targetY: Math.min(targetC, listed - 1e-6), rate: 0, dt }, 6)

        // Zoom so the option at the crosshair fills the screen on arrival
        const frac = focus.b - focus.a
        const targetS = restH * Math.pow(frac, -Math.max(0, Math.min(1, L.progress)))
        L.view = { ...L.view, s: L.view.s + (targetS - L.view.s) * Math.min(1, 10 * dt) }

        if (L.progress >= 1) {
          choose(focus, 'researcher')
        } else if (L.progress < 0) {
          if (L.tokens.length > 0) undo()
          else L.progress = 0
        }
      }

      // The column sits a label's width right of the line at rest and reaches it on arrival
      const gap = L.passed[L.passed.length - 1] ?? (W - crossX) * 0.2
      L.colX = crossX + gap * (1 - Math.max(0, Math.min(1, L.progress)))

      draw(ctx, W, H, crossX, crossY, focus?.id)
      if (!L.cruise) drawGauge(ctx, W, crossX)
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
        const column = layout(shown(L, dist))
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
        // Options shown conditioned: a healed trailing space (they must start a
        // word), or words only
        if (dist[0]?.conditional || L.words) {
          g.fillStyle = color('--text-tertiary')
          g.font = `11px ${color('--font-ui')}`
          g.fillText(
            L.words
              ? 'words only: numbers and symbols hidden (probabilities given a word)'
              : 'given it starts a new word (your text ended in a space)',
            x0 + 8, 34,
          )
        }
        const widths: number[] = []
        L.hits = []
        drawColumn(g, column, ids, top, L.view.s, 0, x0, W, H, color, widths, [], focusId)
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

    // Where the pointer sets the pace: back · hold · forward, and where it is now
    const drawGauge = (g: CanvasRenderingContext2D, W: number, crossX: number) => {
      const css = getComputedStyle(canvas)
      const color = (name: string) => css.getPropertyValue(name).trim() || '#888'
      const { holdL, holdR } = zones(crossX, W)
      const y = 4
      g.globalAlpha = 0.9
      g.fillStyle = color('--border')
      g.fillRect(0, y, holdL, 3)
      g.fillStyle = color('--bg-hover')
      g.fillRect(holdL, y, holdR - holdL, 3)
      const grad = g.createLinearGradient(holdR, 0, W, 0)
      grad.addColorStop(0, color('--bg-hover'))
      grad.addColorStop(1, color('--accent'))
      g.fillStyle = grad
      g.fillRect(holdR, y, W - holdR, 3)
      g.globalAlpha = 1
      g.fillStyle = color('--text-tertiary')
      g.font = `10px ${color('--font-ui')}`
      g.textBaseline = 'top'
      g.fillText('hold', holdL + 4, y + 6)
      g.fillText('faster →', W - 52, y + 6)
      if (holdL > 40) g.fillText('← back', 4, y + 6)
      g.textBaseline = 'alphabetic'
      if (L.pointer.inside) {
        g.fillStyle = color('--text-accent')
        g.fillRect(L.pointer.x - 1, y - 2, 2, 7)
      }
    }

    // One column of options, all starting at x so their labels line up; each
    // option's own next tokens form the column to its right, inside it.
    const drawColumn = (
      g: CanvasRenderingContext2D, column: Box[], prefix: number[], top: number, height: number,
      depth: number, x: number, W: number, H: number, color: (n: string) => string,
      widths: number[], path: Box[], focusId?: number,
    ) => {
      if (x >= W - 8) return
      const crossY = H / 2
      const childX = x + (L.colWidths[depth] ?? 80)
      for (const box of column) {
        const y = top + box.a * height
        const h = (box.b - box.a) * height
        if (y > H || y + h < 0 || h < 0.5) continue
        L.hits.push({ x, y, h, path: [...path, box] })
        const isStop = L.stops.includes(box.token)
        const focused = depth === 0 && box.id === focusId
        g.fillStyle = isStop
          ? color('--accent')
          : focused ? color('--bg-selected')
            : (box.rank + depth) % 2 === 0 ? color('--bg-secondary') : color('--bg-hover')
        g.globalAlpha = isStop ? (focused ? 0.4 : 0.22) : 1
        g.fillRect(x, y, W - x, h)
        g.globalAlpha = 1
        g.strokeStyle = isStop ? color('--accent') : color('--border-subtle')
        g.lineWidth = 1
        g.strokeRect(x + 0.5, y + 0.5, W - x - 1, h - 1)

        if (h > 11) {
          const size = Math.max(10, Math.min(26, h * 0.32))
          g.font = `${size}px ${color('--font-mono')}`
          g.textBaseline = 'middle'
          const label = isStop ? '↵ end of turn' : tokenLabel(box.token)
          // Keep the label on screen, and level with the crosshair when the box spans it
          const labelY = h > 60
            ? Math.max(Math.max(y, 0) + size, Math.min(Math.min(y + h, H) - size, crossY))
            : y + h / 2
          g.fillStyle = focused || isStop ? color('--text-accent') : color('--text-primary')
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
        if (depth < MAX_DEPTH && (!isStop || L.pastEnd) && h > 60) {
          const childIds = [...prefix, box.id]
          const children = L.cache.get(keyOf(childIds))
          if (!children) fetchDist(childIds)
          else {
            drawColumn(
              g, layout(shown(L, children)), childIds, y, h, depth + 1, childX, W, H, color, widths,
              [...path, box],
            )
          }
        }
      }
    }

    frame = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(frame)
  }, [session, choose, undo, fetchDist])

  // A click on an option takes it, and every option on the way to it; elsewhere, pause
  const onCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (yourTurn) return
    const L = live.current
    const rect = e.currentTarget.getBoundingClientRect()
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top
    // Deeper options are drawn over their parents: the last one under the click is it
    const hit = [...L.hits].reverse().find((b) => px >= b.x && py >= b.y && py < b.y + b.h)
    if (!hit || L.ended) {
      setPaused((p) => !p)
      return
    }
    for (const box of hit.path) {
      if (L.ended) break
      choose(box, 'researcher')
    }
  }

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
            <button
              className={`steer-close${confirmClose ? ' confirming' : ''}`}
              onClick={requestClose}
              onBlur={() => setConfirmClose(false)}
              aria-label="Close steering"
              title="Close (Esc)"
            >
              {confirmClose ? `Discard ${tokens.length} token${tokens.length === 1 ? '' : 's'}?` : '×'}
            </button>
          </div>

          <div className="steer-label">Context (end)</div>
          <pre className="steer-context">{context.slice(-600)}</pre>

          <div className="steer-label">
            Reply
          </div>
          <div className="steer-text">
            {tokens.map((t, i) => (
              <span
                key={i}
                title={`${(t.prob * 100).toFixed(2)}%`}
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
              {cruise ? 'Cruise: on' : 'Cruise: off'}
            </button>
            <button
              onClick={() => setPastEnd((v) => !v)}
              className={pastEnd ? 'active' : ''}
              title="Steer through end of turn into the model's version of the next turn"
            >
              Past end of turn
            </button>
            <button
              onClick={() => setWords((v) => !v)}
              className={words ? 'active' : ''}
              title="Hide numbers and symbols; show the options given the next token is a word"
            >
              Words only
            </button>
          </div>

          <label className="steer-slider">
            <span>Speed</span>
            <input type="range" min={0.3} max={3} step={0.1} value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))} />
          </label>

          <p className="steer-help">
            Space: go/pause · point up/down to steer · just right of the line holds, further
            right goes faster, left of the line backs up (see the bar at the top) · Backspace:
            undo · 1–9 (paused): take a ranked token · click a box: take it · Enter: end turn · Esc: close
          </p>

          {error && (
            <div className="steer-error">
              {error}
              <button
                className="steer-retry"
                onClick={() => {
                  live.current.failed.clear()
                  setError(null)
                }}
              >
                Retry
              </button>
            </div>
          )}

          <div className="steer-actions">
            <button className="steer-discard" onClick={requestClose}>
              {confirmClose ? 'Really discard?' : 'Discard'}
            </button>
            <button
              className="steer-keep"
              onClick={() => keep({ thenYourTurn: false })}
              disabled={saving || tokens.length === 0 || yourTurn != null}
              title="Save the reply as it stands and close"
            >
              {saving ? 'Saving…' : 'Keep so far'}
            </button>
            <button
              className="steer-keep"
              onClick={endTurn}
              disabled={saving || tokens.length === 0 || yourTurn != null || ended}
              title="End the turn here and write yours (Enter)"
            >
              End turn
            </button>
          </div>
        </div>

        <div className="steer-stage">
          <canvas
            ref={canvasRef}
            className="steer-canvas"
            onPointerMove={onPointer}
            onPointerEnter={onPointer}
            onPointerLeave={() => { live.current.pointer.inside = false }}
            onClick={onCanvasClick}
          />
          {yourTurn && (
            <div className="steer-your-turn">
              <div className="steer-label">Your turn</div>
              <p className="steer-help">
                {turnFromOpen ? 'The conversation ends on her turn.' : 'Her reply is kept.'}{' '}
                Write yours; Enter sends it and steers her next reply.
              </p>
              <textarea
                autoFocus
                rows={3}
                value={myMessage}
                onChange={(e) => setMyMessage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void sendMyTurn()
                  } else if (e.key === 'Escape') {
                    onClose()
                  }
                }}
                placeholder="Your message…"
              />
              <div className="steer-actions">
                <button className="steer-discard" onClick={onClose}>Done</button>
                {turnFromOpen && (
                  <button
                    className="steer-discard"
                    onClick={() => { setYourTurn(null); setTurnFromOpen(false) }}
                    title="Steer another turn of hers after this one"
                  >
                    Steer her next turn instead
                  </button>
                )}
                <button className="steer-keep" onClick={() => void sendMyTurn()} disabled={!myMessage.trim()}>
                  Send and steer her reply
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
