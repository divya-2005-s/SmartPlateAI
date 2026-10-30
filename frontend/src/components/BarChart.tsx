/** Small accessible SVG bar chart (no chart library). Null values are drawn as "no data", never as zero. */
type Bar = { label: string; value: number | null; incomplete?: boolean }

export default function BarChart({ bars, unit, title, height = 180 }: { bars: Bar[]; unit: string; title: string; height?: number }) {
  const max = Math.max(1, ...bars.map((b) => b.value ?? 0))
  const w = 100 / Math.max(1, bars.length)
  const top = height - 30
  return (
    <figure className="w-full">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="h-48 w-full" role="img" aria-label={`${title} (${unit})`}>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1="0" x2="100" y1={top - f * (top - 10)} y2={top - f * (top - 10)} stroke="#0f2a24" strokeOpacity="0.07" strokeWidth="0.3" />
        ))}
        {bars.map((b, i) => {
          const h = b.value === null ? 0 : (b.value / max) * (top - 10)
          return (
            <g key={b.label}>
              <title>{`${b.label}: ${b.value === null ? 'no data' : `${Math.round(b.value)} ${unit}`}${b.incomplete ? ' (incomplete)' : ''}`}</title>
              {b.value === null ? (
                <rect x={i * w + w * 0.2} y={top - 2} width={w * 0.6} height={2} fill="#94a3b8" />
              ) : (
                <rect x={i * w + w * 0.2} y={top - h} width={w * 0.6} height={Math.max(h, 0.5)} rx="1" fill={b.incomplete ? '#f59e0b' : '#059669'} />
              )}
            </g>
          )
        })}
      </svg>
      <div className="grid text-center text-[11px] text-ink-soft" style={{ gridTemplateColumns: `repeat(${bars.length}, minmax(0, 1fr))` }}>
        {bars.map((b) => (
          <span key={b.label} className="truncate">
            {b.label}
            <span className="block font-semibold text-ink">{b.value === null ? '–' : Math.round(b.value)}</span>
          </span>
        ))}
      </div>
      <figcaption className="mt-2 flex flex-wrap gap-4 text-xs text-ink-soft">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-emerald-600" />{title} ({unit})</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-amber-500" />some items missing this value</span>
        <span><span className="mr-1 inline-block h-0.5 w-2 bg-slate-400 align-middle" />no data</span>
      </figcaption>
    </figure>
  )
}
