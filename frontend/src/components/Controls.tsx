import type { LibrarySummary, PackParams, RenderOptions, ShapeInfo } from '../types'

interface SliderProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  // Explicitly `| undefined` because exactOptionalPropertyTypes rejects a
  // prop passed as undefined unless the type admits it.
  suffix?: string | undefined
  hint?: string | undefined
  decimals?: number | undefined
  onChange: (value: number) => void
}

function Slider({
  label, value, min, max, step, suffix, hint, decimals = 2, onChange,
}: SliderProps) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between">
        <span className="text-xs font-medium text-neutral-300">{label}</span>
        <span className="font-mono text-xs text-neutral-400">
          {value.toFixed(decimals)}{suffix ?? ''}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => { onChange(Number(event.target.value)) }}
        className="mt-1.5 w-full accent-amber-400"
      />
      {hint && <span className="mt-0.5 block text-[11px] leading-snug text-neutral-500">{hint}</span>}
    </label>
  )
}

function Toggle({
  label, checked, hint, disabled, onChange,
}: {
  label: string
  checked: boolean
  hint?: string | undefined
  disabled?: boolean | undefined
  onChange: (value: boolean) => void
}) {
  return (
    <div>
      <label className={`flex cursor-pointer items-center gap-2.5
                        ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled ?? false}
          onChange={(event) => { onChange(event.target.checked) }}
          className="h-3.5 w-3.5 rounded border-neutral-600 bg-neutral-900 accent-amber-400"
        />
        <span className="text-xs font-medium text-neutral-300">{label}</span>
      </label>
      {hint && (
        <span className="mt-0.5 block pl-6 text-[11px] leading-snug text-neutral-500">
          {hint}
        </span>
      )}
    </div>
  )
}

interface Props {
  params: PackParams
  onParams: (patch: Partial<PackParams>) => void
  render: RenderOptions
  onRender: (patch: Partial<RenderOptions>) => void
  /** Total attachment points defined by the selected library. */
  attachPointCount: number
  libraries: LibrarySummary[]
  libraryId: string
  onLibrary: (id: string) => void
  calibMm: number
  onCalibMm: (value: number) => void
  needsScale: boolean
  unitsPerMm: number | null
  onUnitsPerMm: (value: number) => void
  shapes: ShapeInfo[]
  shapeIds: string[] | null
  onShapeIds: (ids: string[] | null) => void
  unitsPerMmEffective: number | null
  disabled: boolean
}

export function Controls({
  params, onParams, render, onRender, attachPointCount,
  libraries, libraryId, onLibrary,
  calibMm, onCalibMm, needsScale, unitsPerMm, onUnitsPerMm,
  shapes, shapeIds, onShapeIds, unitsPerMmEffective, disabled,
}: Props) {
  const chosen = new Set(
    shapeIds ?? shapes.filter((s) => s.auto_selected).map((s) => s.id),
  )
  const anyPainted = shapes.some((s) => s.filled)

  const toggleShape = (id: string) => {
    const next = new Set(chosen)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onShapeIds(next.size === 0 ? null : [...next])
  }

  const areaMm2 = (shape: ShapeInfo) =>
    unitsPerMmEffective && unitsPerMmEffective > 0
      ? shape.area_units / (unitsPerMmEffective * unitsPerMmEffective)
      : null
  const library = libraries.find((entry) => entry.id === libraryId)
  const [lo, hi] = library?.size_range_mm ?? [0, 0]

  return (
    <div className={disabled ? 'space-y-6 opacity-40 pointer-events-none' : 'space-y-6'}>
      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Library
        </h2>
        <select
          value={libraryId}
          onChange={(event) => { onLibrary(event.target.value) }}
          className="w-full rounded-md border border-neutral-700 bg-neutral-900 px-2.5 py-1.5
                     text-sm text-neutral-100 focus:border-amber-400 focus:outline-none"
        >
          {libraries.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.name} ({entry.piece_count} pieces)
            </option>
          ))}
        </select>
        {library && (
          <p className="text-[11px] leading-snug text-neutral-500">
            {(lo ?? 0).toFixed(1)}–{(hi ?? 0).toFixed(1)} mm at 1×, so{' '}
            <span className="text-neutral-400">
              {((lo ?? 0) * params.piece_scale).toFixed(0)}–
              {((hi ?? 0) * params.piece_scale).toFixed(0)} mm
            </span>{' '}
            at the current scale. Rapport density{' '}
            {(library.rapport_coverage * 100).toFixed(0)}%.
          </p>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Scale reference
        </h2>
        {needsScale ? (
          <label className="block">
            <span className="text-xs font-medium text-neutral-300">Units per mm</span>
            <input
              type="number"
              min={0.0001}
              step="any"
              value={unitsPerMm ?? ''}
              onChange={(event) => { onUnitsPerMm(Number(event.target.value)) }}
              className="mt-1 w-full rounded-md border border-amber-600/60 bg-neutral-900
                         px-2.5 py-1.5 text-sm text-neutral-100 focus:border-amber-400
                         focus:outline-none"
            />
            <span className="mt-1 block text-[11px] leading-snug text-amber-500/80">
              No <code className="font-mono">id="calib"</code> element in this file, so the
              scale cannot be read from it. Enter units/mm directly — it is never guessed.
            </span>
          </label>
        ) : (
          <label className="block">
            <span className="text-xs font-medium text-neutral-300">
              Width of <code className="font-mono text-[11px]">#calib</code> in mm
            </span>
            <input
              type="number"
              min={0.01}
              step="any"
              value={calibMm}
              onChange={(event) => { onCalibMm(Number(event.target.value)) }}
              className="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-900
                         px-2.5 py-1.5 text-sm text-neutral-100 focus:border-amber-400
                         focus:outline-none"
            />
          </label>
        )}
      </section>

      {shapes.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
            Region to fill
          </h2>
          <ul className="space-y-1">
            {shapes.map((shape) => {
              const mm2 = areaMm2(shape)
              return (
                <li key={shape.id || shape.tag}>
                  <label className="flex cursor-pointer items-center gap-2.5">
                    <input
                      type="checkbox"
                      checked={chosen.has(shape.id)}
                      onChange={() => { toggleShape(shape.id) }}
                      className="h-3.5 w-3.5 rounded border-neutral-600 bg-neutral-900
                                 accent-amber-400"
                    />
                    <span className="min-w-0 flex-1 truncate font-mono text-xs
                                     text-neutral-300">
                      {shape.id || `<${shape.tag}>`}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-neutral-500">
                      {mm2 === null ? '—' : `${(mm2 / 1e6).toFixed(2)} m²`}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
          {!anyPainted && (
            <p className="text-[11px] leading-snug text-neutral-500">
              Nothing in this file is filled, so the largest outline was taken as
              the panel. If that picked a seam line, choose the right one here.
            </p>
          )}
        </section>
      )}

      <section className="space-y-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Density
        </h2>
        <Slider
          label="Piece scale" value={params.piece_scale} min={0.5} max={6} step={0.1}
          suffix="×" decimals={1}
          onChange={(value) => { onParams({ piece_scale: value }) }}
        />
        <Slider
          label="Minimum gap" value={params.min_gap_mm} min={0} max={10} step={0.1}
          suffix=" mm" decimals={1}
          onChange={(value) => { onParams({ min_gap_mm: value }) }}
        />
        <Slider
          label="Target coverage" value={params.target_coverage * 100} min={5} max={90}
          step={1} suffix="%" decimals={0}
          hint="Packing stops once this is reached. 56% is MARBLE's own rapport density."
          onChange={(value) => { onParams({ target_coverage: value / 100 }) }}
        />
        <Slider
          label="Edge clearance" value={params.edge_clearance_mm} min={0} max={25} step={0.5}
          suffix=" mm" decimals={1}
          hint="Keeps pieces back from the panel edge, for seam allowance."
          onChange={(value) => { onParams({ edge_clearance_mm: value }) }}
        />
      </section>

      <section className="space-y-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Colour blocking
        </h2>
        <Slider
          label="Bands" value={params.bands} min={1} max={8} step={1} decimals={0}
          hint={params.bands === 1 ? 'One colour across the whole panel.' : undefined}
          onChange={(value) => { onParams({ bands: value }) }}
        />
        {params.bands > 1 && (
          <>
            <Slider
              label="Band angle" value={params.band_angle_deg} min={0} max={355} step={5}
              suffix="°" decimals={0}
              onChange={(value) => { onParams({ band_angle_deg: value }) }}
            />
            <Slider
              label="Band bleed" value={params.band_jitter_mm} min={0} max={120} step={1}
              suffix=" mm" decimals={0}
              hint="Softens the boundary so colours interleave instead of stopping dead."
              onChange={(value) => { onParams({ band_jitter_mm: value }) }}
            />
          </>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Markers
        </h2>
        <Toggle
          label="Attachment points"
          checked={render.showAttach}
          disabled={attachPointCount === 0}
          hint={
            attachPointCount === 0
              ? 'This library defines no attachment points.'
              : `Dots where each piece is stitched down — ${attachPointCount} across ` +
                'the library. Redraws instantly; it does not re-pack.'
          }
          onChange={(value) => { onRender({ showAttach: value }) }}
        />
      </section>

      <section className="space-y-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          Export
        </h2>
        <Toggle
          label="Plain paths"
          checked={render.expand}
          hint={
            'Writes every piece as its own path instead of one reused definition. '
            + 'Several times larger, and the thing to try when the download opens '
            + 'empty somewhere.'
          }
          onChange={(value) => { onRender({ expand: value }) }}
        />
      </section>

      <details className="group">
        <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase
                            tracking-wider text-neutral-500 hover:text-neutral-400">
          Advanced
        </summary>
        <div className="mt-4 space-y-4">
          <Slider
            label="Rotation steps" value={params.rotation_steps} min={1} max={72} step={1}
            decimals={0}
            hint="Distinct angles a piece may take. 1 means no rotation."
            onChange={(value) => { onParams({ rotation_steps: value }) }}
          />
          <Slider
            label="Packing passes" value={params.max_passes} min={1} max={16} step={1}
            decimals={0}
            hint="More passes chase the last few percent of coverage, and cost time."
            onChange={(value) => { onParams({ max_passes: value }) }}
          />
          <Slider
            label="Grid resolution" value={params.grid_res} min={1} max={6} step={0.5}
            suffix=" cells/mm" decimals={1}
            hint="Finer is more exact and slower. The gap rounds to whole cells."
            onChange={(value) => { onParams({ grid_res: value }) }}
          />
          <label className="block">
            <span className="text-xs font-medium text-neutral-300">Seed</span>
            <div className="mt-1 flex gap-2">
              <input
                type="number"
                value={params.seed}
                onChange={(event) => { onParams({ seed: Math.abs(Math.trunc(Number(event.target.value))) }) }}
                className="w-full rounded-md border border-neutral-700 bg-neutral-900 px-2.5
                           py-1.5 font-mono text-xs text-neutral-100 focus:border-amber-400
                           focus:outline-none"
              />
              <button
                type="button"
                onClick={() => { onParams({ seed: Math.floor(Math.random() * 2 ** 31) }) }}
                className="shrink-0 rounded-md bg-neutral-800 px-3 text-xs text-neutral-300
                           hover:bg-neutral-700"
              >
                shuffle
              </button>
            </div>
            <span className="mt-0.5 block text-[11px] text-neutral-500">
              The same seed and settings always give the same layout.
            </span>
          </label>
        </div>
      </details>
    </div>
  )
}
