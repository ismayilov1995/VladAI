import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { LibraryDetail, PackResponse, Placement } from '../types'
import { PALETTE, PANEL_EDGE, PANEL_FILL, colourForClass } from '../lib/palette'

/**
 * Canvas 2-D preview.
 *
 * Never SVG DOM: a panel at working density runs to thousands of pieces, and
 * that many <use> nodes stalls the browser. SVG exists only in the downloaded
 * file.
 *
 * Even on canvas, one stroke call per piece is wasteful. Pieces are gathered
 * into one Path2D per colour class, so a pack of any size costs about as many
 * draw calls as there are colours.
 */

interface View {
  scale: number   // device pixels per millimetre
  x: number       // device-pixel offset
  y: number
}

interface Props {
  pack: PackResponse | null
  library: LibraryDetail | null
  pieceScale: number
  busy: boolean
}

function piecePath(rings: number[][], scale: number): Path2D {
  const path = new Path2D()
  for (const ring of rings) {
    if (ring.length < 6) continue
    path.moveTo((ring[0] ?? 0) * scale, (ring[1] ?? 0) * scale)
    for (let i = 2; i < ring.length; i += 2) {
      path.lineTo((ring[i] ?? 0) * scale, (ring[i + 1] ?? 0) * scale)
    }
    path.closePath()
  }
  return path
}

function panelPath(panels: PackResponse['panels']): Path2D {
  const path = new Path2D()
  for (const panel of panels) {
    for (const ring of panel.rings) {
      if (ring.length < 6) continue
      path.moveTo(ring[0] ?? 0, ring[1] ?? 0)
      for (let i = 2; i < ring.length; i += 2) {
        path.lineTo(ring[i] ?? 0, ring[i + 1] ?? 0)
      }
      path.closePath()
    }
  }
  return path
}

export function PreviewCanvas({ pack, library, pieceScale, busy }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [size, setSize] = useState({ width: 800, height: 600 })
  const [view, setView] = useState<View | null>(null)
  const dragRef = useRef<{ x: number; y: number; view: View } | null>(null)

  // Piece outlines are stable for a library and scale, so build them once and
  // reuse across every redraw.
  const pieceShapes = useMemo(() => {
    const shapes = new Map<string, Path2D>()
    if (!library) return shapes
    for (const piece of library.pieces) {
      shapes.set(piece.id, piecePath(piece.rings, pieceScale))
    }
    return shapes
  }, [library, pieceScale])

  const outline = useMemo(() => (pack ? panelPath(pack.panels) : null), [pack])

  const bounds = useMemo(() => {
    if (!pack || pack.panels.length === 0) return null
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const panel of pack.panels) {
      const [x0, y0, x1, y1] = panel.bbox
      minX = Math.min(minX, x0 ?? 0)
      minY = Math.min(minY, y0 ?? 0)
      maxX = Math.max(maxX, x1 ?? 0)
      maxY = Math.max(maxY, y1 ?? 0)
    }
    return Number.isFinite(minX) ? { minX, minY, maxX, maxY } : null
  }, [pack])

  useLayoutEffect(() => {
    const element = wrapRef.current
    if (!element) return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect && rect.width > 0 && rect.height > 0) {
        setSize({ width: Math.round(rect.width), height: Math.round(rect.height) })
      }
    })
    observer.observe(element)
    return () => { observer.disconnect() }
  }, [])

  const fit = useCallback(() => {
    if (!bounds) return
    const dpr = window.devicePixelRatio || 1
    const pad = 24 * dpr
    const width = size.width * dpr
    const height = size.height * dpr
    const spanX = Math.max(bounds.maxX - bounds.minX, 1e-6)
    const spanY = Math.max(bounds.maxY - bounds.minY, 1e-6)
    const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY)
    setView({
      scale,
      x: (width - spanX * scale) / 2 - bounds.minX * scale,
      y: (height - spanY * scale) / 2 - bounds.minY * scale,
    })
  }, [bounds, size.width, size.height])

  // Re-fit when a different panel arrives or the viewport changes shape, but
  // leave the view alone while the user is only adjusting parameters.
  const fitKey = bounds
    ? `${bounds.minX},${bounds.minY},${bounds.maxX},${bounds.maxY},${size.width},${size.height}`
    : ''
  useEffect(() => { fit() }, [fitKey, fit])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const width = Math.round(size.width * dpr)
    const height = Math.round(size.height * dpr)
    if (canvas.width !== width) canvas.width = width
    if (canvas.height !== height) canvas.height = height

    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.fillStyle = '#14121a'
    ctx.fillRect(0, 0, width, height)
    if (!view || !pack) return

    ctx.setTransform(view.scale, 0, 0, view.scale, view.x, view.y)

    if (outline) {
      ctx.fillStyle = PANEL_FILL
      ctx.fill(outline, 'nonzero')
      ctx.lineWidth = 1 / view.scale
      ctx.strokeStyle = PANEL_EDGE
      ctx.stroke(outline)
    }

    // Bucket placements by colour class, then stroke each bucket once.
    const buckets = new Map<string, Path2D>()
    for (const placement of pack.placements as Placement[]) {
      const shape = pieceShapes.get(placement.piece)
      if (!shape) continue
      let bucket = buckets.get(placement.cls)
      if (!bucket) {
        bucket = new Path2D()
        buckets.set(placement.cls, bucket)
      }
      const matrix = new DOMMatrix()
        .translateSelf(placement.x, placement.y)
        .rotateSelf(placement.angle)
      bucket.addPath(shape, matrix)
    }

    // A hairline in device pixels regardless of zoom, so a zoomed-out panel
    // still reads as stitching rather than a solid block.
    ctx.lineWidth = Math.max(0.6 / view.scale, 0.06)
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'
    for (const [cls, path] of buckets) {
      ctx.strokeStyle = colourForClass(cls)
      ctx.stroke(path)
    }
  }, [pack, view, size, pieceShapes, outline])

  const onWheel = useCallback((event: React.WheelEvent<HTMLCanvasElement>) => {
    if (!view) return
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    const px = (event.clientX - rect.left) * dpr
    const py = (event.clientY - rect.top) * dpr
    const factor = Math.exp(-event.deltaY * 0.0015)
    const scale = Math.min(Math.max(view.scale * factor, 1e-4), 4000)
    const ratio = scale / view.scale
    // Keep the point under the cursor fixed while zooming.
    setView({ scale, x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio })
  }, [view])

  const onPointerDown = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!view) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { x: event.clientX, y: event.clientY, view }
  }, [view])

  const onPointerMove = useCallback((event: React.PointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const dpr = window.devicePixelRatio || 1
    setView({
      scale: drag.view.scale,
      x: drag.view.x + (event.clientX - drag.x) * dpr,
      y: drag.view.y + (event.clientY - drag.y) * dpr,
    })
  }, [])

  const endDrag = useCallback(() => { dragRef.current = null }, [])

  const classes = useMemo(() => {
    if (!pack) return []
    const seen = new Set(pack.placements.map((p) => p.cls))
    return [...seen].sort()
  }, [pack])

  return (
    <div ref={wrapRef} className="relative h-full w-full overflow-hidden bg-[#14121a]">
      <canvas
        ref={canvasRef}
        className="h-full w-full touch-none"
        style={{ cursor: dragRef.current ? 'grabbing' : 'grab' }}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      />

      {busy && (
        <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-full bg-black/70
                        px-4 py-1.5 text-xs font-medium text-white/90 backdrop-blur">
          packing…
        </div>
      )}

      {!pack && !busy && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center
                        text-sm text-white/40">
          drop a panel SVG to begin
        </div>
      )}

      <div className="absolute bottom-3 left-3 flex items-center gap-2">
        <button
          type="button"
          onClick={fit}
          className="rounded-md bg-white/10 px-2.5 py-1 text-xs text-white/80
                     hover:bg-white/20"
        >
          fit
        </button>
        {classes.length > 1 && (
          <div className="flex items-center gap-1.5 rounded-md bg-black/50 px-2 py-1">
            {classes.map((cls) => (
              <span key={cls} className="flex items-center gap-1 text-[10px] text-white/70">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: colourForClass(cls) }}
                />
                {cls}
              </span>
            ))}
          </div>
        )}
      </div>
      <span className="sr-only">{PALETTE.length} thread colours available</span>
    </div>
  )
}
