import { Link } from 'react-router-dom'
import { Leaf } from 'lucide-react'

export default function Logo({ light = false }: { light?: boolean }) {
  return (
    <Link to="/" className="inline-flex items-center gap-2.5" aria-label="SmartPlateAI home">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-sm">
        <Leaf className="h-5 w-5" aria-hidden="true" />
      </span>
      <span
        className={`font-display text-lg font-extrabold tracking-tight ${light ? 'text-white' : 'text-ink'}`}
      >
        SmartPlate<span className={light ? 'text-emerald-300' : 'text-emerald-600'}>AI</span>
      </span>
    </Link>
  )
}