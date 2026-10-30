import { useState } from 'react'
import { Salad } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

type Props = { src: string; alt: string; className?: string; eager?: boolean; position?: string; fallbackIcon?: LucideIcon }

export default function ImageSlot({ src, alt, className = '', eager = false, position = 'center', fallbackIcon: Icon = Salad }: Props) {
  const [failed, setFailed] = useState(false)

  if (failed) {
    return (
      <div
        role="img"
        aria-label={alt}
        className={`relative grid place-items-center overflow-hidden bg-gradient-to-br from-emerald-100 via-teal-50 to-amber-50 ${className}`}
      >
        <span className="flex flex-col items-center gap-2 text-emerald-800/70">
          <Icon className="h-10 w-10" aria-hidden="true" />
          <span className="text-xs font-semibold">Photo not available</span>
        </span>
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      onError={() => setFailed(true)}
      style={{ objectPosition: position }}
      className={`bg-emerald-50 object-cover ${className}`}
    />
  )
}