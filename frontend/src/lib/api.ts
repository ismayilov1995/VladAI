import type {
  LibraryDetail, LibrarySummary, PackParams, PackResponse, UploadResponse,
} from '../types'

export class ApiError extends Error {
  readonly status: number
  /** Set when the server reports it cannot scale the document by itself. */
  readonly needsScale: boolean

  constructor(message: string, status: number, needsScale = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.needsScale = needsScale
  }
}

async function readError(response: Response): Promise<never> {
  let detail = `${response.status} ${response.statusText}`
  let needsScale = false
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object') {
      const record = body as Record<string, unknown>
      needsScale = record['needs_scale'] === true
      const raw = record['detail']
      if (typeof raw === 'string') detail = raw
      else if (Array.isArray(raw) && raw.length > 0) {
        // FastAPI validation errors arrive as a list of issues.
        detail = raw
          .map((issue) => {
            const item = issue as Record<string, unknown>
            const loc = Array.isArray(item['loc']) ? item['loc'].join('.') : ''
            return `${loc}: ${String(item['msg'] ?? 'invalid')}`
          })
          .join('; ')
      }
    }
  } catch {
    // Body was not JSON; the status line is the best message available.
  }
  throw new ApiError(detail, response.status, needsScale)
}

export async function listLibraries(): Promise<LibrarySummary[]> {
  const response = await fetch('/api/libraries')
  if (!response.ok) await readError(response)
  return (await response.json()) as LibrarySummary[]
}

export async function getLibrary(id: string): Promise<LibraryDetail> {
  const response = await fetch(`/api/libraries/${encodeURIComponent(id)}`)
  if (!response.ok) await readError(response)
  return (await response.json()) as LibraryDetail
}

export async function uploadPanel(file: File): Promise<UploadResponse> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/api/upload', { method: 'POST', body })
  if (!response.ok) await readError(response)
  return (await response.json()) as UploadResponse
}

export interface PackArgs {
  fileId: string
  library: string
  calibMm: number
  unitsPerMm: number | null
  shapeIds: string[] | null
  params: PackParams
  signal?: AbortSignal
}

export async function packPanel(args: PackArgs): Promise<PackResponse> {
  const response = await fetch('/api/pack', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_id: args.fileId,
      library: args.library,
      calib_mm: args.calibMm,
      units_per_mm: args.unitsPerMm,
      shape_ids: args.shapeIds,
      params: args.params,
    }),
    ...(args.signal ? { signal: args.signal } : {}),
  })
  if (!response.ok) await readError(response)
  return (await response.json()) as PackResponse
}
