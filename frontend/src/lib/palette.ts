/** Thread colours for the colour-blocking classes A, B, C, ... */
export const PALETTE: readonly string[] = [
  '#e8e3d9', // raw silk
  '#c9a227', // old gold
  '#8c7851', // bronze
  '#7d8c8a', // sage grey
  '#a63d40', // madder red
  '#4a5c6a', // indigo grey
  '#d9c7a7', // ecru
  '#2f3e46', // near black
]

/** Panel ground, so the preview reads like the fabric rather than a chart. */
export const PANEL_FILL = '#2f2a33'
export const PANEL_EDGE = '#6d6377'

export function colourForClass(cls: string): string {
  const index = Math.max(0, (cls.codePointAt(0) ?? 65) - 65)
  return PALETTE[index % PALETTE.length] ?? '#ffffff'
}
