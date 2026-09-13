/** Mirrors the FastAPI contract in backend/app/models.py. */

export interface PackParams {
  piece_scale: number
  min_gap_mm: number
  target_coverage: number
  seed: number
  grid_res: number
  rotation_steps: number
  max_passes: number
  edge_clearance_mm: number
  bands: number
  band_angle_deg: number
  band_jitter_mm: number
}

export interface ShapeInfo {
  id: string
  tag: string
  area_units: number
  bbox: number[]
}

export interface UploadResponse {
  file_id: string
  filename: string
  width_units: number
  height_units: number
  view_box: number[] | null
  calib_width_units: number | null
  /** True when the document has no id="calib"; the scale is never guessed. */
  needs_scale: boolean
  shapes: ShapeInfo[]
}

/** One piece placed on the panel. Position is the centroid, in millimetres. */
export interface Placement {
  piece: string
  x: number
  y: number
  angle: number
  cls: string
}

export interface PanelOutline {
  id: string
  fill_rule: string
  bbox: number[]
  /** Flat [x0, y0, x1, y1, ...] rings in millimetres. */
  rings: number[][]
}

export interface PackStats {
  count: number
  coverage: number
  covered_mm2: number
  region_mm2: number
  grid_res?: number
  note?: string
}

export interface PackResponse {
  units_per_mm: number
  panels: PanelOutline[]
  placements: Placement[]
  stats: PackStats
  cached: boolean
  elapsed_ms: number
}

export interface LibraryPiece {
  id: string
  /** Flat coordinate rings in millimetres, centred on the piece's centroid. */
  rings: number[][]
  area_mm2: number
  width_mm: number
  height_mm: number
  attach: number[][]
}

export interface LibrarySummary {
  id: string
  name: string
  unit: string
  description: string
  provenance: string
  rapport_coverage: number
  piece_count: number
  size_range_mm: number[]
}

export interface LibraryDetail extends LibrarySummary {
  pieces: LibraryPiece[]
}

export const DEFAULT_PARAMS: PackParams = {
  piece_scale: 2.0,
  min_gap_mm: 1.0,
  // MARBLE's own rapport density, and the designer's intended default.
  target_coverage: 0.56,
  seed: 20260913,
  grid_res: 2.0,
  rotation_steps: 24,
  max_passes: 8,
  edge_clearance_mm: 0,
  bands: 1,
  band_angle_deg: 0,
  band_jitter_mm: 0,
}

/** Above this the browser starts to feel the piece count; the UI warns. */
export const PIECE_COUNT_WARNING = 5000
