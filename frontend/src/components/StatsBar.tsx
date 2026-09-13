import type { PackResponse } from '../types'
import { PIECE_COUNT_WARNING } from '../types'

interface Props {
  pack: PackResponse | null
  target: number
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-neutral-500">{label}</div>
      <div className={`font-mono text-sm ${tone ?? 'text-neutral-200'}`}>{value}</div>
    </div>
  )
}

export function StatsBar({ pack, target }: Props) {
  if (!pack) return null
  const { stats } = pack
  const heavy = stats.count > PIECE_COUNT_WARNING
  const shortfall = stats.coverage < target - 0.02

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-4 gap-3">
        <Figure
          label="pieces"
          value={stats.count.toLocaleString()}
          tone={heavy ? 'text-amber-400' : 'text-neutral-200'}
        />
        <Figure label="coverage" value={`${(stats.coverage * 100).toFixed(1)}%`} />
        <Figure label="area" value={`${(stats.region_mm2 / 1e6).toFixed(2)} m²`} />
        <Figure
          label="pack"
          value={pack.cached ? 'cached' : `${(pack.elapsed_ms / 1000).toFixed(1)}s`}
          tone={pack.cached ? 'text-emerald-400' : 'text-neutral-200'}
        />
      </div>

      {heavy && (
        <p className="rounded-md bg-amber-500/10 px-2.5 py-1.5 text-[11px] leading-snug
                      text-amber-300/90">
          {stats.count.toLocaleString()} pieces is a heavy file. Raising the piece scale or
          the minimum gap cuts the count sharply.
        </p>
      )}

      {shortfall && !heavy && (
        <p className="rounded-md bg-neutral-800/80 px-2.5 py-1.5 text-[11px] leading-snug
                      text-neutral-400">
          Packing saturated at {(stats.coverage * 100).toFixed(1)}%, below the{' '}
          {(target * 100).toFixed(0)}% target — the panel has no room left for another
          piece at this scale and gap.
        </p>
      )}

      {stats.note && (
        <p className="rounded-md bg-red-500/10 px-2.5 py-1.5 text-[11px] text-red-300/90">
          {stats.note}
        </p>
      )}
    </div>
  )
}
