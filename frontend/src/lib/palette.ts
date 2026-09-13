/**
 * Thread colours for the colour-blocking classes A, B, C, ...
 *
 * One palette serves both the preview and the export, so what you download is
 * what you saw. That constrains it: the preview draws on dark fabric, while an
 * exported SVG almost always opens on a white artboard, so every colour has to
 * stay legible on both. Near-whites and near-blacks are therefore out, however
 * good they look on one of the two — an earlier raw-silk `#e8e3d9` read
 * beautifully on the fabric and arrived in Illustrator as a blank panel.
 *
 * Contrast against `#2f2a33` and `#ffffff` respectively, lowest first:
 * madder 2.2/6.2, moss 2.9/4.9, lavender 2.9/4.8, bronze 3.3/4.3,
 * slate 3.2/4.4, terracotta 3.6/3.9, sage 4.0/3.5, gold 4.5/3.1.
 */
export const PALETTE: readonly string[] = [
  '#b08d57', // antique gold
  '#a63d40', // madder red
  '#5f7d8c', // slate blue
  '#4a7c59', // moss
  '#c06c3e', // terracotta
  '#7a6a9b', // lavender
  '#8c7851', // bronze
  '#7d8c8a', // sage
]

/** Panel ground, so the preview reads like the fabric rather than a chart. */
export const PANEL_FILL = '#2f2a33'
export const PANEL_EDGE = '#6d6377'

export function colourForClass(cls: string): string {
  const index = Math.max(0, (cls.codePointAt(0) ?? 65) - 65)
  return PALETTE[index % PALETTE.length] ?? '#b08d57'
}
