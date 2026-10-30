import { Link } from 'react-router-dom'
import Logo from '../Logo'

const linkClass = 'text-sm text-ink-soft transition-colors hover:text-emerald-700'

export default function Footer() {
  return (
    <footer className="border-t border-emerald-900/10 bg-white">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-3 lg:px-8">
        <div>
          <Logo />
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-ink-soft">
            Food recognition, label reading and nutrition insight in one place. SmartPlateAI supports
            food awareness. It is not a substitute for laboratory testing, food-safety inspection or
            medical advice.
          </p>
        </div>
        <nav aria-label="Product">
          <h3 className="font-display text-sm font-bold text-ink">Product</h3>
          <ul className="mt-4 space-y-3">
            <li><Link className={linkClass} to="/#features">Features</Link></li>
            <li><Link className={linkClass} to="/#how-it-works">How it works</Link></li>
            <li><Link className={linkClass} to="/#trust">Accuracy &amp; safety</Link></li>
          </ul>
        </nav>
        <nav aria-label="Get started">
          <h3 className="font-display text-sm font-bold text-ink">Get started</h3>
          <ul className="mt-4 space-y-3">
            <li><Link className={linkClass} to="/analyze">Analyze Food</Link></li>
          </ul>
        </nav>
      </div>
      <div className="border-t border-emerald-900/10 py-6 text-center text-xs text-ink-soft">
        © {new Date().getFullYear()} SmartPlateAI. Nutrition values are reference estimates.
      </div>
    </footer>
  )
}