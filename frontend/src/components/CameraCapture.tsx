import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Camera, ImagePlus, SwitchCamera, X } from 'lucide-react'

/** guide: on-screen framing aid. 'food' = one item in the centre, 'package' = the whole pack side, 'closeup' = barcode or table. */
type Guide = 'food' | 'package' | 'closeup'
type Props = { onCapture: (file: File) => void; onClose: () => void; label?: string; guide?: Guide }

const GUIDE_TEXT: Record<Guide, string> = {
  food: 'Place one food inside the circle, in good light',
  package: 'Fit the whole side of the pack inside the frame',
  closeup: 'Fill the frame with the barcode or the nutrition table; hold steady',
}

function cameraErrorMessage(e: unknown): string {
  const name = e instanceof DOMException ? e.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'Camera permission was denied. Allow camera access in your browser settings, or upload a photo instead.'
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No camera was found on this device. Upload a photo instead.'
  if (name === 'NotReadableError') return 'The camera is being used by another app. Close it and try again.'
  return 'The camera could not be started. Upload a photo instead.'
}

export default function CameraCapture({ onCapture, onClose, label = 'Capture photo', guide = 'food' }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [facing, setFacing] = useState<'environment' | 'user'>('environment')
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const stop = () => {
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    setReady(false)
    setError(null)
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(window.isSecureContext
        ? 'This browser does not support camera capture. Upload a photo instead.'
        : 'Camera access needs a secure page (https or localhost). Upload a photo instead.')
      return
    }
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: { ideal: facing }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        stop()
        streamRef.current = stream
        const v = videoRef.current
        if (v) {
          v.srcObject = stream
          v.play().then(() => setReady(true)).catch(() => setReady(true))
        }
      })
      .catch((e: unknown) => { if (!cancelled) setError(cameraErrorMessage(e)) })
    return () => {
      cancelled = true
      stop()
    }
  }, [facing])

  const capture = () => {
    const v = videoRef.current
    if (!v || !v.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = v.videoWidth
    canvas.height = v.videoHeight
    canvas.getContext('2d')?.drawImage(v, 0, 0)
    canvas.toBlob((blob) => {
      if (!blob) return setError('Could not capture the photo. Please try again.')
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
      onCapture(new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' }))
    }, 'image/jpeg', 0.92)
  }

  const pickFallback = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (f) onCapture(f)
  }

  return (
    <div className="rounded-2xl border border-emerald-900/10 bg-ink/95 p-3 text-white">
      <div className="relative overflow-hidden rounded-xl bg-black">
        <video ref={videoRef} playsInline muted className="aspect-[4/3] w-full object-cover" aria-label="Live camera preview" />
        {ready && !error && (
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 grid place-items-center">
            <div className={guide === 'food' ? 'aspect-square w-[58%] rounded-full border-2 border-dashed border-white/80'
              : guide === 'closeup' ? 'h-[45%] w-[80%] rounded-xl border-2 border-dashed border-white/80'
              : 'h-[82%] w-[70%] rounded-2xl border-2 border-dashed border-white/80'} />
            <p className="absolute bottom-2 left-2 right-2 rounded-lg bg-black/50 px-2 py-1 text-center text-xs text-white">{GUIDE_TEXT[guide]}</p>
          </div>
        )}
        {!ready && !error && (
          <div role="status" className="absolute inset-0 grid place-items-center text-sm text-white/80">Starting camera…</div>
        )}
        {error && (
          <div role="alert" className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-sm font-semibold">
            <p>{error}</p>
            {/* Fallback: the phone's own camera app through a file input works without camera permission in the page. */}
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-white px-4 py-2 text-ink hover:bg-emerald-50">
              <ImagePlus className="h-4 w-4" aria-hidden="true" /> Take or choose a photo
              <input type="file" accept="image/*" capture="environment" className="sr-only" onChange={pickFallback} />
            </label>
          </div>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={onClose} className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-white/90 hover:bg-white/10">
          <X className="h-4 w-4" aria-hidden="true" /> Close camera
        </button>
        <div className="flex gap-2">
          <button type="button" onClick={() => setFacing((f) => (f === 'environment' ? 'user' : 'environment'))} disabled={!!error}
            className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-white/90 hover:bg-white/10 disabled:opacity-40">
            <SwitchCamera className="h-4 w-4" aria-hidden="true" /> Switch
          </button>
          <button type="button" onClick={capture} disabled={!ready || !!error}
            className="inline-flex items-center gap-2 rounded-full bg-emerald-500 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-400 disabled:opacity-40">
            <Camera className="h-4 w-4" aria-hidden="true" /> {label}
          </button>
        </div>
      </div>
    </div>
  )
}
