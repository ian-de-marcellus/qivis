/**
 * Custom hook for SVG zoom/pan via pointer events.
 * Wheel zooms toward cursor; drag pans. No external dependencies.
 *
 * Wheel listener is attached as a native non-passive event so that
 * preventDefault() actually works and the browser doesn't also zoom the page.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

interface ZoomPanTransform {
  scale: number
  translateX: number
  translateY: number
}

interface UseZoomPanOptions {
  minScale?: number
  maxScale?: number
}

export function useZoomPan(options?: UseZoomPanOptions) {
  const minScale = options?.minScale ?? 0.15
  const maxScale = options?.maxScale ?? 3

  const [transform, setTransform] = useState<ZoomPanTransform>({
    scale: 1,
    translateX: 0,
    translateY: 0,
  })

  const isPanning = useRef(false)
  const panStart = useRef({ x: 0, y: 0 })
  const transformRef = useRef(transform)
  transformRef.current = transform

  // Ref for the element that receives wheel events
  const wheelRef = useRef<SVGSVGElement | null>(null)

  // Attach native wheel listener with { passive: false } so preventDefault works
  useEffect(() => {
    const el = wheelRef.current
    if (!el) return

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault()
      const { scale, translateX, translateY } = transformRef.current
      const zoomFactor = e.deltaY < 0 ? 1.08 : 1 / 1.08
      const newScale = Math.min(maxScale, Math.max(minScale, scale * zoomFactor))

      const rect = el.getBoundingClientRect()
      const cursorX = e.clientX - rect.left
      const cursorY = e.clientY - rect.top

      const newTranslateX = cursorX - ((cursorX - translateX) / scale) * newScale
      const newTranslateY = cursorY - ((cursorY - translateY) / scale) * newScale

      setTransform({
        scale: newScale,
        translateX: newTranslateX,
        translateY: newTranslateY,
      })
    }

    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [minScale, maxScale])

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return
    const target = e.target as HTMLElement
    if (target.closest('.graph-node-hit')) return

    isPanning.current = true
    panStart.current = { x: e.clientX, y: e.clientY }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!isPanning.current) return
    const dx = e.clientX - panStart.current.x
    const dy = e.clientY - panStart.current.y
    panStart.current = { x: e.clientX, y: e.clientY }

    setTransform((prev) => ({
      ...prev,
      translateX: prev.translateX + dx,
      translateY: prev.translateY + dy,
    }))
  }, [])

  const onPointerUp = useCallback(() => {
    isPanning.current = false
  }, [])

  const fitToContent = useCallback(
    (contentWidth: number, contentHeight: number, containerWidth: number, containerHeight: number) => {
      if (contentWidth <= 0 || contentHeight <= 0 || containerWidth <= 0 || containerHeight <= 0) {
        setTransform({ scale: 1, translateX: 0, translateY: 0 })
        return
      }

      const padding = 60
      const scaleX = (containerWidth - padding * 2) / contentWidth
      const scaleY = (containerHeight - padding * 2) / contentHeight
      const scale = Math.min(scaleX, scaleY, 2)
      const finalScale = Math.max(minScale, scale)

      const translateX = (containerWidth - contentWidth * finalScale) / 2
      const translateY = (containerHeight - contentHeight * finalScale) / 2

      setTransform({ scale: finalScale, translateX, translateY })
    },
    [minScale],
  )

  return {
    transform,
    wheelRef,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
    },
    fitToContent,
    isPanning,
  }
}
