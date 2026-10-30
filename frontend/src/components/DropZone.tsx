import { useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { Upload } from 'lucide-react'

type Props = {
  title: string
  hint: string
  onFile: (f: File) => void
  disabled?: boolean
  compact?: boolean
  accept?: string
  inputLabel?: string
}

/** Click-to-upload area that also accepts a dropped image. Validation stays with the caller (size/type checks). */
export default function DropZone({ title, hint, onFile, disabled = false, compact = false,
  accept = 'image/jpeg,image/png,image/webp', inputLabel }: Props) {
  const [over, setOver] = useState(false)
  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (f) onFile(f)
  }
  const drop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault()
    setOver(false)
    if (disabled) return
    const f = e.dataTransfer.files?.[0]
    if (f) onFile(f)
  }
  return (
    <label
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={`group flex h-full cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed text-center transition
        focus-within:ring-4 focus-within:ring-emerald-600/20 ${compact ? 'min-h-36 px-4 py-6' : 'min-h-52 px-6 py-10'}
        ${over ? 'border-emerald-500 bg-emerald-50' : 'border-emerald-300 bg-emerald-50/40 hover:border-emerald-400 hover:bg-emerald-50'}
        ${disabled ? 'pointer-events-none opacity-60' : ''}`}
    >
      <span className={`grid place-items-center rounded-full bg-white text-emerald-600 shadow-sm ring-1 ring-emerald-900/5 transition group-hover:scale-105 ${compact ? 'h-10 w-10' : 'h-14 w-14'}`}>
        <Upload className={compact ? 'h-5 w-5' : 'h-6 w-6'} aria-hidden="true" />
      </span>
      <span className={`font-semibold text-ink ${compact ? 'text-sm' : 'text-base'}`}>{title}</span>
      <span className="text-xs text-ink-soft"><span className="hidden sm:inline">Drag and drop, or click to browse. </span>{hint}</span>
      <input type="file" accept={accept} className="sr-only" onChange={pick} disabled={disabled} aria-label={inputLabel} />
    </label>
  )
}
