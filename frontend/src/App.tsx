import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Controls } from './components/Controls'
import { DropZone } from './components/DropZone'
import { PreviewCanvas } from './components/PreviewCanvas'
import { StatsBar } from './components/StatsBar'
import { ApiError, getLibrary, listLibraries, packPanel, uploadPanel } from './lib/api'
import { buildFilledSvg, downloadText, filledFilename } from './lib/svgExport'
import { DEFAULT_PARAMS, DEFAULT_RENDER_OPTIONS } from './types'
import type {
  LibraryDetail, LibrarySummary, PackParams, PackResponse, RenderOptions, UploadResponse,
} from './types'

/** Settling time before a slider change becomes a pack request. */
const DEBOUNCE_MS = 400

interface PanelState {
  upload: UploadResponse
  /** The file's own text, kept so the download can be built without a round trip. */
  svgText: string
}

export function App() {
  const [libraries, setLibraries] = useState<LibrarySummary[]>([])
  const [libraryId, setLibraryId] = useState('marble')
  const [library, setLibrary] = useState<LibraryDetail | null>(null)

  const [panel, setPanel] = useState<PanelState | null>(null)
  const [params, setParams] = useState<PackParams>(DEFAULT_PARAMS)
  // Render options are deliberately not part of `params`: they change how the
  // pack is drawn, not what was packed, so they must never trigger a re-pack.
  const [render, setRender] = useState<RenderOptions>(DEFAULT_RENDER_OPTIONS)
  const [calibMm, setCalibMm] = useState(100)
  const [unitsPerMm, setUnitsPerMm] = useState<number | null>(null)
  // null means "let the server decide", which is the right default.
  const [shapeIds, setShapeIds] = useState<string[] | null>(null)

  const [pack, setPack] = useState<PackResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  // Guards against a slow earlier pack landing after a faster later one.
  const requestSeq = useRef(0)

  useEffect(() => {
    listLibraries()
      .then((entries) => {
        setLibraries(entries)
        if (entries.length > 0 && !entries.some((e) => e.id === libraryId)) {
          setLibraryId(entries[0]?.id ?? 'marble')
        }
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : 'could not reach the API')
      })
    // Only on mount: this seeds the picker, it must not re-run on every change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    let live = true
    getLibrary(libraryId)
      .then((detail) => { if (live) setLibrary(detail) })
      .catch(() => { if (live) setLibrary(null) })
    return () => { live = false }
  }, [libraryId])

  const onFile = useCallback(async (file: File) => {
    setReading(true)
    setError(null)
    try {
      const [svgText, upload] = await Promise.all([file.text(), uploadPanel(file)])
      setPanel({ upload, svgText })
      setPack(null)
      setShapeIds(null)
      // A file that carries no calib element needs the scale typed in. Seed the
      // box with the document's own units so the number is a starting point
      // rather than a blank, but never treat it as a measurement.
      setUnitsPerMm(upload.needs_scale ? 1 : null)
    } catch (cause: unknown) {
      setPanel(null)
      setError(cause instanceof Error ? cause.message : 'upload failed')
    } finally {
      setReading(false)
    }
  }, [])

  const patchParams = useCallback((patch: Partial<PackParams>) => {
    setParams((current) => ({ ...current, ...patch }))
  }, [])

  const patchRender = useCallback((patch: Partial<RenderOptions>) => {
    setRender((current) => ({ ...current, ...patch }))
  }, [])

  // Re-pack whenever anything that affects the result settles.
  useEffect(() => {
    if (!panel) return
    if (panel.upload.needs_scale && !(unitsPerMm && unitsPerMm > 0)) return

    const timer = window.setTimeout(() => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      const seq = ++requestSeq.current

      setBusy(true)
      packPanel({
        fileId: panel.upload.file_id,
        library: libraryId,
        calibMm,
        unitsPerMm: panel.upload.needs_scale ? unitsPerMm : null,
        shapeIds,
        params,
        signal: controller.signal,
      })
        .then((result) => {
          if (seq !== requestSeq.current) return
          setPack(result)
          setError(null)
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted || seq !== requestSeq.current) return
          if (cause instanceof ApiError && cause.needsScale) {
            setError('This file has no id="calib" element — enter units/mm to continue.')
          } else {
            setError(cause instanceof Error ? cause.message : 'packing failed')
          }
        })
        .finally(() => {
          if (seq === requestSeq.current) setBusy(false)
        })
    }, DEBOUNCE_MS)

    return () => { window.clearTimeout(timer) }
  }, [panel, libraryId, calibMm, unitsPerMm, shapeIds, params])

  useEffect(() => () => { abortRef.current?.abort() }, [])

  const canDownload = Boolean(pack && library && panel && pack.placements.length > 0)

  const onDownload = useCallback(() => {
    if (!pack || !library || !panel) return
    const svg = buildFilledSvg({
      originalSvg: panel.svgText,
      library,
      placements: pack.placements,
      pieceScale: params.piece_scale,
      unitsPerMm: pack.units_per_mm,
      showAttach: render.showAttach,
      expand: !render.compact,
    })
    downloadText(filledFilename(panel.upload.filename), svg)
  }, [pack, library, panel, params.piece_scale, render.showAttach, render.compact])

  const provenance = useMemo(
    () => libraries.find((entry) => entry.id === libraryId)?.provenance ?? '',
    [libraries, libraryId],
  )

  const attachPointCount = useMemo(
    () => library?.pieces.reduce((total, piece) => total + piece.attach.length, 0) ?? 0,
    [library],
  )

  return (
    <div className="flex h-full">
      <aside className="flex w-[340px] shrink-0 flex-col overflow-hidden border-r
                        border-neutral-800 bg-neutral-950">
        {/* Scrolling controls above, pinned stats and download below, so the
            piece count and the download button never fall off the bottom. */}
        <div className="scroll-slim flex flex-1 flex-col gap-5 overflow-y-auto p-5">
        <header>
          <h1 className="text-lg font-semibold tracking-tight text-neutral-100">Vlada AI</h1>
          <p className="text-[11px] text-neutral-500">embroidery fill</p>
        </header>

        <DropZone
          filename={panel?.upload.filename ?? null}
          busy={reading}
          onFile={(file) => { void onFile(file) }}
        />

        {error && (
          <p className="rounded-md bg-red-500/10 px-2.5 py-2 text-[11px] leading-snug
                        text-red-300">
            {error}
          </p>
        )}

        <Controls
          params={params}
          onParams={patchParams}
          render={render}
          onRender={patchRender}
          attachPointCount={attachPointCount}
          libraries={libraries}
          libraryId={libraryId}
          onLibrary={setLibraryId}
          calibMm={calibMm}
          onCalibMm={setCalibMm}
          needsScale={panel?.upload.needs_scale ?? false}
          unitsPerMm={unitsPerMm}
          onUnitsPerMm={setUnitsPerMm}
          shapes={panel?.upload.shapes ?? []}
          shapeIds={shapeIds}
          onShapeIds={setShapeIds}
          unitsPerMmEffective={pack?.units_per_mm ?? null}
          disabled={!panel}
        />

        </div>

        <div className="space-y-3 border-t border-neutral-800 bg-neutral-950 p-5">
          <StatsBar pack={pack} target={params.target_coverage} />
          <button
            type="button"
            disabled={!canDownload}
            onClick={onDownload}
            className="w-full rounded-md bg-amber-400 px-3 py-2 text-sm font-medium
                       text-neutral-950 transition hover:bg-amber-300
                       disabled:cursor-not-allowed disabled:bg-neutral-800
                       disabled:text-neutral-600"
          >
            Download filled SVG
          </button>
          <p className="text-[10px] leading-snug text-neutral-600">
            The fill is appended as one group; your uploaded file is never modified.
          </p>
          {provenance.startsWith('SYNTHESISED') && (
            <p className="text-[10px] leading-snug text-amber-600/70">
              Stand-in library — outlines are generated, not the traced originals.
            </p>
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <PreviewCanvas
          pack={pack}
          library={library}
          pieceScale={params.piece_scale}
          busy={busy}
          showAttach={render.showAttach}
        />
      </main>
    </div>
  )
}
