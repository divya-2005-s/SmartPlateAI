import { Link } from 'react-router-dom'
import Navbar from '../components/layout/Navbar'
import Footer from '../components/layout/Footer'

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="grid flex-1 place-items-center px-4 py-24 text-center">
        <div>
          <p className="font-display text-7xl font-extrabold text-emerald-600">404</p>
          <h1 className="mt-4 font-display text-2xl font-bold">This page isn&rsquo;t on the menu</h1>
          <p className="mt-2 text-ink-soft">The page you&rsquo;re looking for doesn&rsquo;t exist or has moved.</p>
          <Link
            to="/"
            className="mt-8 inline-block rounded-full bg-emerald-600 px-7 py-3 font-semibold text-white shadow-md hover:bg-emerald-700"
          >
            Back to home
          </Link>
        </div>
      </main>
      <Footer />
    </div>
  )
}