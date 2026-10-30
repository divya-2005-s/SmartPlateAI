import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Apple, Package, ShieldCheck } from 'lucide-react'
import FoodAnalyzer from '../components/FoodAnalyzer'
import PackagedAnalyzer from '../components/PackagedAnalyzer'
import ChatPanel from '../components/ChatPanel'
import Navbar from '../components/layout/Navbar'
import Footer from '../components/layout/Footer'
import type { AnalysisContext } from '../lib/chatApi'
import { setCurrentAnalysis } from '../lib/analysisContext'

type Mode = 'fresh' | 'packaged'

function PublicFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-cream text-ink">
      <Navbar />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 pb-20 pt-8 sm:px-6 lg:px-8 lg:pt-12">
        {children}
      </main>
      <Footer />
    </div>
  )
}

export default function AnalyzePage({
  initialMode = 'fresh',
  inShell = false,
}: {
  initialMode?: Mode
  inShell?: boolean
}) {
  const [mode, setMode] = useState<Mode>(initialMode)
  const [freshCtx, setFreshCtx] = useState<AnalysisContext | null>(null)
  const [packagedCtx, setPackagedCtx] = useState<AnalysisContext | null>(null)
  const onFresh = useCallback((context: AnalysisContext | null) => setFreshCtx(context), [])
  const onPackaged = useCallback((context: AnalysisContext | null) => setPackagedCtx(context), [])
  const context = mode === 'fresh' ? freshCtx : packagedCtx
  useEffect(() => {
    if (context) setCurrentAnalysis(context)
  }, [context])

  const tab = (selectedMode: Mode, label: string, Icon: typeof Apple, hint: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === selectedMode}
      aria-controls={`panel-${selectedMode}`}
      id={`tab-${selectedMode}`}
      onClick={() => setMode(selectedMode)}
      className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-2xl px-3 py-3 text-left transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-emerald-600/20 sm:gap-3 sm:px-4 ${
        mode === selectedMode
          ? 'bg-white shadow-soft ring-1 ring-emerald-900/10'
          : 'text-ink-soft hover:bg-white/60'
      }`}
    >
      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${mode === selectedMode ? 'bg-emerald-50 text-emerald-600' : 'bg-white/70'}`}>
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold leading-tight text-ink sm:text-base">{label}</span>
        <span className="hidden truncate text-xs sm:block">{hint}</span>
      </span>
    </button>
  )

  const body = (
    <div className="@container text-ink">
      <header className="flex flex-col gap-5 @4xl:flex-row @4xl:items-end @4xl:justify-between">
        <div className="max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-wider text-emerald-600">Food analysis</p>
          <h1 className="mt-1 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">Analyse your food</h1>
          <p className="mt-3 text-base leading-relaxed text-ink-soft">
            Photograph or upload any meal, fruit, vegetable or snack, or the front and back of a packaged food.
            Results show where every value comes from and what is not known.
          </p>
        </div>
        <div role="tablist" aria-label="Food type" className="flex w-full gap-1.5 rounded-3xl bg-emerald-900/5 p-1.5 @4xl:w-[30rem] @4xl:shrink-0">
          {tab('fresh', 'Unpackaged food', Apple, 'Meals, fruit, vegetables')}
          {tab('packaged', 'Packaged food', Package, 'Label photos or barcode')}
        </div>
      </header>

      <div className="mt-8 grid items-start gap-6 @3xl:grid-cols-[minmax(0,1fr)_22rem] @6xl:grid-cols-[minmax(0,1fr)_24rem] @6xl:gap-8">
        <div className="min-w-0">
          {/* Keep both analyzers mounted so switching modes preserves each result. */}
          <div id="panel-fresh" role="tabpanel" aria-labelledby="tab-fresh" hidden={mode !== 'fresh'}>
            <FoodAnalyzer embedded active={mode === 'fresh'} onContextChange={onFresh} />
          </div>
          <div id="panel-packaged" role="tabpanel" aria-labelledby="tab-packaged" hidden={mode !== 'packaged'}>
            <PackagedAnalyzer active={mode === 'packaged'} onContextChange={onPackaged} />
          </div>
          <p className="mt-6 flex items-start gap-2 text-xs text-ink-soft">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" aria-hidden="true" />
            Reference information, not medical advice. Nutrition is matched to databases or read from the label, never measured from the photo.
          </p>
        </div>
        <aside
          aria-label="Ask SmartPlate"
          className={`min-w-0 @3xl:sticky ${inShell ? '@3xl:top-8 @3xl:h-[calc(100vh-4rem)]' : '@3xl:top-24 @3xl:h-[calc(100vh-8rem)]'} @3xl:max-h-[52rem]`}
        >
          <ChatPanel context={context} />
        </aside>
      </div>
    </div>
  )

  return inShell ? body : <PublicFrame>{body}</PublicFrame>
}
