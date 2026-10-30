import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  CalendarDays,
  Camera,
  Check,
  Database,
  FlaskConical,
  MessageCircle,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Upload,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Navbar from '../components/layout/Navbar'
import Footer from '../components/layout/Footer'
import Reveal from '../components/Reveal'
import ImageSlot from '../components/ImageSlot'

const macros = [
  { label: 'Energy', value: '52', unit: 'kcal' },
  { label: 'Carbs', value: '13.8', unit: 'g' },
  { label: 'Protein', value: '0.3', unit: 'g' },
  { label: 'Fat', value: '0.2', unit: 'g' },
]

const features: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: Camera,
    title: 'Fresh food recognition',
    text: 'Upload a photo of fruit, vegetables or prepared food and get the most likely food category with a confidence score.',
  },
  {
    icon: ScanLine,
    title: 'Packaged label scanning',
    text: 'Photograph a nutrition label and ingredient list. Text is extracted so you can review and correct it.',
  },
  {
    icon: Activity,
    title: 'Clear nutrition breakdown',
    text: 'Energy, macronutrients, fiber, sugars, sodium and vitamins, shown with their reference basis. Missing values stay marked as unavailable.',
  },
  {
    icon: FlaskConical,
    title: 'Ingredients & additives',
    text: 'Look up additive (INS) codes and see their function and regulatory context, without alarmist labelling.',
  },
  {
    icon: MessageCircle,
    title: 'AI nutrition assistant',
    text: 'Ask questions about your results. Answers are grounded in trusted food-information sources.',
  },
  {
    icon: CalendarDays,
    title: 'Healthy diet planner',
    text: 'Get meal suggestions with approximate nutrition that respect your dietary preferences.',
  },
]

const steps: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Upload, title: 'Upload or scan', text: 'Add a food photo or a packaged-food label from your device.' },
  { icon: Sparkles, title: 'AI analyses it', text: 'A vision model identifies the food, or OCR reads the label text.' },
  { icon: Database, title: 'Matched to trusted data', text: 'Results are linked to reference nutrition and additive information.' },
  { icon: ShieldCheck, title: 'Understand and plan', text: 'Review plain-language explanations, then chat or build a meal plan.' },
]

const trust = [
  {
    title: 'Reference estimates, not lab results',
    text: 'A photo identifies a food. Nutrition values come from reference databases such as USDA FoodData Central, not from measuring your individual item.',
  },
  {
    title: 'Missing data is never shown as zero',
    text: 'If a nutrient is not available, we say so instead of filling in a number.',
  },
  {
    title: 'Uncertain predictions are flagged',
    text: 'Low-confidence results are labelled so you can double-check before relying on them.',
  },
  {
    title: 'Support, not medical advice',
    text: 'SmartPlateAI supports food awareness. Talk to a qualified professional for medical or dietary decisions.',
  },
]

export default function Landing() {
  return (
    <div className="min-h-screen">
      <Navbar />
      <main>
        {/* Hero */}
        <section className="relative overflow-hidden">
          <div aria-hidden="true" className="pointer-events-none absolute -right-40 -top-40 h-[32rem] w-[32rem] rounded-full bg-emerald-200/40 blur-3xl" />
          <div aria-hidden="true" className="pointer-events-none absolute -left-32 top-48 h-96 w-96 rounded-full bg-teal-200/30 blur-3xl" />

          <div className="relative mx-auto grid max-w-7xl items-center gap-14 px-4 pb-24 pt-12 sm:px-6 lg:grid-cols-2 lg:gap-16 lg:px-8 lg:pb-32 lg:pt-20">
            <div>
              <span className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-white px-3.5 py-1.5 text-xs font-semibold text-emerald-700 shadow-sm">
                <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                Food intelligence, in plain language
              </span>
              <h1 className="mt-6 font-display text-4xl font-extrabold leading-[1.08] tracking-tight text-ink sm:text-5xl lg:text-6xl">
                Know exactly what&rsquo;s on your <span className="text-emerald-600">plate.</span>
              </h1>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-soft">
                Photograph fresh food or scan a packaged label. SmartPlateAI identifies the food, finds
                reference nutrition and explains ingredients and additives, so choosing well gets easier.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-4">
                <Link
                  to="/analyze"
                  className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-7 py-3.5 text-base font-semibold text-white shadow-lg shadow-emerald-600/25 transition hover:-translate-y-0.5 hover:bg-emerald-700"
                >
                  Analyze Food <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Link>
                <Link
                  to="/#how-it-works"
                  className="rounded-full border border-emerald-900/15 bg-white px-7 py-3.5 text-base font-semibold text-ink transition hover:border-emerald-600 hover:text-emerald-700"
                >
                  How it works
                </Link>
              </div>
              <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-soft">
                {['Reference nutrition per 100 g', 'Plain-language additive info', 'Not a medical device'].map((t) => (
                  <li key={t} className="flex items-center gap-2">
                    <Check className="h-4 w-4 text-emerald-600" aria-hidden="true" /> {t}
                  </li>
                ))}
              </ul>
            </div>

            <div className="relative mx-auto mb-10 w-[90%] max-w-md lg:mb-0">
              <div className="overflow-hidden rounded-[2rem] shadow-lift ring-1 ring-black/5">
                <ImageSlot
                  src="/images/hero-apple.jpg"
                  alt="A colourful salad with fresh vegetables and grains"
                  eager
                  position="top"
                  className="aspect-[4/5] w-full object-contain"
                />
              </div>

              <div className="absolute -bottom-8 left-3 right-3 animate-float rounded-2xl bg-white/95 p-5 shadow-lift ring-1 ring-black/5 backdrop-blur sm:-left-8 sm:right-auto sm:w-80">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-display text-lg font-bold text-ink">Apple</p>
                    <p className="text-xs text-ink-soft">Reference values per 100 g · USDA FoodData Central</p>
                  </div>
                  <span className="shrink-0 rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-800">
                    Example layout
                  </span>
                </div>
                <dl className="mt-4 grid grid-cols-4 gap-2">
                  {macros.map((m) => (
                    <div key={m.label} className="rounded-xl bg-emerald-50 px-2 py-2.5 text-center">
                      <dd className="text-sm font-bold text-emerald-800">
                        {m.value}
                        <span className="text-[10px] font-medium"> {m.unit}</span>
                      </dd>
                      <dt className="mt-0.5 text-[10px] text-ink-soft">{m.label}</dt>
                    </div>
                  ))}
                </dl>
                <p className="mt-3 text-[11px] text-ink-soft">
                  Illustrative example of a results card, not a live prediction.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Photo band */}
        <section aria-label="What you can analyse" className="mx-auto max-w-7xl px-4 pb-8 sm:px-6 lg:px-8">
          <div className="grid gap-5 sm:grid-cols-3">
            {[
              { src: '/images/fresh-produce-selected.jpg', alt: 'A single red apple', caption: 'Fresh produce' },
              { src: '/images/packaged-food-selected.jpg', alt: 'Packaged foods with printed labels: cartons, cans, a box of pasta and a loaf of bread', caption: 'Packaged foods' },
              { src: '/images/fresh-produce.jpg', alt: 'Baskets of fresh fruit and vegetables, including grapes, an orange, corn and a red pepper', caption: 'Balanced meals' },
            ].map((p, i) => (
              <Reveal key={p.caption} delay={i * 100}>
                <figure className="relative overflow-hidden rounded-3xl shadow-soft ring-1 ring-black/5">
                  <ImageSlot src={p.src} alt={p.alt} className="aspect-[4/5] w-full sm:aspect-[3/4]" />
                  <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-emerald-950/70 to-transparent" />
                  <figcaption className="absolute bottom-4 left-5 font-display text-lg font-bold text-white">
                    {p.caption}
                  </figcaption>
                </figure>
              </Reveal>
            ))}
          </div>
        </section>

        {/* Features */}
        <section id="features" className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
          <Reveal className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-wider text-emerald-600">Features</p>
            <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
              Everything you need to understand your food
            </h2>
            <p className="mt-4 text-lg text-ink-soft">
              Separate tools for fresh and packaged food, connected by one clear results view.
            </p>
          </Reveal>
          <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((f, i) => (
              <Reveal key={f.title} delay={(i % 3) * 100}>
                <article className="group h-full rounded-3xl border border-emerald-900/10 bg-white p-7 shadow-soft transition duration-300 hover:-translate-y-1 hover:shadow-lift">
                  <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-600/20">
                    <f.icon className="h-6 w-6" aria-hidden="true" />
                  </span>
                  <h3 className="mt-5 font-display text-lg font-bold">{f.title}</h3>
                  <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">{f.text}</p>
                </article>
              </Reveal>
            ))}
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="bg-white py-24">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <Reveal className="mx-auto max-w-2xl text-center">
              <p className="text-sm font-semibold uppercase tracking-wider text-emerald-600">How it works</p>
              <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
                From photo to understanding in four steps
              </h2>
            </Reveal>
            <ol className="mt-14 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
              {steps.map((s, i) => (
                <li key={s.title}>
                  <Reveal delay={i * 100}>
                    <div className="relative h-full rounded-3xl bg-cream p-7 ring-1 ring-emerald-900/10">
                      <span className="absolute right-6 top-5 font-display text-5xl font-extrabold text-emerald-600/10">
                        {i + 1}
                      </span>
                      <span className="grid h-11 w-11 place-items-center rounded-xl bg-emerald-100 text-emerald-700">
                        <s.icon className="h-5 w-5" aria-hidden="true" />
                      </span>
                      <h3 className="mt-5 font-display text-lg font-bold">{s.title}</h3>
                      <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">{s.text}</p>
                    </div>
                  </Reveal>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Trust */}
        <section id="trust" className="mx-auto max-w-7xl px-4 py-24 sm:px-6 lg:px-8">
          <div className="grid items-start gap-12 lg:grid-cols-5">
            <Reveal className="lg:col-span-2">
              <p className="text-sm font-semibold uppercase tracking-wider text-emerald-600">Accuracy &amp; safety</p>
              <h2 className="mt-3 font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
                Honest about what AI can and can&rsquo;t tell you
              </h2>
              <p className="mt-4 text-lg leading-relaxed text-ink-soft">
                A photo can&rsquo;t reveal exact chemical content. We show reference estimates, flag
                uncertainty and keep sources visible, so you can make informed choices.
              </p>
            </Reveal>
            <div className="grid gap-5 sm:grid-cols-2 lg:col-span-3">
              {trust.map((t, i) => (
                <Reveal key={t.title} delay={(i % 2) * 100}>
                  <div className="h-full rounded-3xl border border-emerald-900/10 bg-white p-6 shadow-soft">
                    <ShieldCheck className="h-6 w-6 text-emerald-600" aria-hidden="true" />
                    <h3 className="mt-3 font-display text-base font-bold">{t.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-ink-soft">{t.text}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="px-4 pb-24 sm:px-6 lg:px-8">
          <Reveal>
            <div className="mx-auto max-w-5xl rounded-[2rem] bg-gradient-to-br from-emerald-600 to-teal-700 px-6 py-16 text-center shadow-lift sm:px-12">
              <h2 className="font-display text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
                Start understanding your food today
              </h2>
              <p className="mx-auto mt-4 max-w-xl text-lg text-emerald-50">
                Analyse fresh food or packaged labels right away. No account is required.
              </p>
              <div className="mt-8 flex flex-wrap justify-center gap-4">
                <Link
                  to="/analyze"
                  className="rounded-full bg-white px-7 py-3.5 text-base font-semibold text-emerald-700 shadow-md transition hover:-translate-y-0.5"
                >
                  Analyze Food
                </Link>
                <Link
                  to="/#features"
                  className="rounded-full border border-white/40 px-7 py-3.5 text-base font-semibold text-white transition hover:bg-white/10"
                >
                  Explore features
                </Link>
              </div>
            </div>
          </Reveal>
        </section>
      </main>
      <Footer />
    </div>
  )
}