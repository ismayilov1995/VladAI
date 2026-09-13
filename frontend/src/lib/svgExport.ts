/**
 * Build the downloadable SVG from the placement list.
 *
 * The preview canvas and this file are drawn from the same pack response, so
 * what you download is what you previewed. The structure matters in a few
 * specific ways:
 *
 *  - One `<g id="mpNN">` per library piece in `<defs>`, centred on its own
 *    centroid, so `rotate()` spins a piece in place rather than swinging it
 *    around the document origin.
 *  - `transform="translate(x y) rotate(a)"` in that order: rotate about the
 *    piece's own origin first, then move it into position.
 *  - Colour goes on the `stroke` **attribute** of each `<use>`. It cannot be a
 *    stylesheet rule: `<use>` clones its referent into a shadow tree that
 *    outside selectors do not reach, so `#mosaic .A path {}` silently matches
 *    nothing. Inherited presentation attributes on the `<use>` itself do cross
 *    into the clone, which is why an attribute works where CSS does not.
 *  - The uploaded document is passed through untouched and the fill is
 *    appended as one group, so deleting that group restores the original.
 */

import type { LibraryDetail, Placement } from '../types'
import { ATTACH_DOT_RADIUS_MM } from '../types'
import { colourForClass } from './palette'

export const FILL_GROUP_ID = 'mosaic-fill'

function fmt(value: number, places = 3): string {
  const text = value.toFixed(places).replace(/\.?0+$/, '')
  return text === '' || text === '-0' ? '0' : text
}

/** Path data for one piece, scaled into user units, still centroid-centred. */
export function piecePathData(rings: number[][], factor: number): string {
  const parts: string[] = []
  for (const ring of rings) {
    if (ring.length < 6) continue
    const points: string[] = []
    for (let i = 0; i < ring.length; i += 2) {
      points.push(`${fmt((ring[i] ?? 0) * factor)},${fmt((ring[i + 1] ?? 0) * factor)}`)
    }
    parts.push(`M${points.join(' L')} Z`)
  }
  return parts.join(' ')
}

export interface BuildOptions {
  originalSvg: string
  library: LibraryDetail
  placements: readonly Placement[]
  pieceScale: number
  unitsPerMm: number
  strokeWidthMm?: number | undefined
  /** Mark each piece's stitch-down points. */
  showAttach?: boolean | undefined
  attachDotRadiusMm?: number | undefined
}

const CLOSING_SVG = /<\/svg\s*>\s*$/i

export function buildFilledSvg(options: BuildOptions): string {
  const { originalSvg, library, placements, pieceScale, unitsPerMm } = options
  const strokeWidthMm = options.strokeWidthMm ?? 0.25
  const showAttach = options.showAttach ?? false
  const dotRadius = (options.attachDotRadiusMm ?? ATTACH_DOT_RADIUS_MM) * unitsPerMm

  // Piece scale and units/mm are baked into the defs geometry, which is what
  // lets every <use> carry nothing but a translate and a rotate.
  const factor = pieceScale * unitsPerMm
  const symbolFor = new Map<string, string>()
  const defs: string[] = []

  library.pieces.forEach((piece, index) => {
    const symbolId = `mp${String(index + 1).padStart(2, '0')}`
    symbolFor.set(piece.id, symbolId)
    const data = piecePathData(piece.rings, factor)
    if (!data) return
    let body = `<path fill="none" d="${data}"/>`
    if (showAttach && dotRadius > 0) {
      // Dots sit inside the piece's own group, so the <use> transform carries
      // them along for free. `currentColor` picks up the `color` attribute set
      // on each <use>, which like `stroke` is inherited and so reaches into
      // the shadow tree that a stylesheet rule could not.
      for (const point of piece.attach) {
        const ax = point[0]
        const ay = point[1]
        if (ax === undefined || ay === undefined) continue
        body +=
          `<circle cx="${fmt(ax * factor)}" cy="${fmt(ay * factor)}" ` +
          `r="${fmt(dotRadius)}" fill="currentColor" stroke="none"/>`
      }
    }
    defs.push(`  <g id="${symbolId}">${body}</g>`)
  })

  const uses: string[] = []
  for (const placement of placements) {
    const symbolId = symbolFor.get(placement.piece)
    if (symbolId === undefined) continue
    const x = fmt(placement.x * unitsPerMm)
    const y = fmt(placement.y * unitsPerMm)
    const angle = fmt(placement.angle, 2)
    const transform = angle === '0'
      ? `translate(${x} ${y})`
      : `translate(${x} ${y}) rotate(${angle})`
    const colour = colourForClass(placement.cls)
    // `color` only earns its bytes when there are dots to tint.
    const tint = showAttach ? ` color="${colour}"` : ''
    uses.push(
      `  <use href="#${symbolId}" transform="${transform}" stroke="${colour}"${tint}/>`,
    )
  }

  const addition =
    `<defs>\n${defs.join('\n')}\n</defs>\n` +
    `<g id="${FILL_GROUP_ID}" fill="none" ` +
    `stroke-width="${fmt(strokeWidthMm * unitsPerMm)}" ` +
    `stroke-linejoin="round" stroke-linecap="round">\n` +
    `${uses.join('\n')}\n</g>\n`

  const match = CLOSING_SVG.exec(originalSvg)
  if (!match) {
    // No closing tag to insert before. Appending keeps the fill rather than
    // dropping it silently.
    return `${originalSvg}\n${addition}`
  }
  return `${originalSvg.slice(0, match.index)}${addition}</svg>\n`
}

export function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Revoke on the next tick so the click has certainly been handled.
  setTimeout(() => { URL.revokeObjectURL(url) }, 0)
}

export function filledFilename(original: string): string {
  const base = original.replace(/\.svg$/i, '')
  return `${base || 'panel'}-filled.svg`
}
