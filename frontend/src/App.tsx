import { useEffect } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './components/AuthProvider'
import AnalyzePage from './pages/AnalyzePage'
import Landing from './pages/Landing'
import AuthPage from './pages/AuthPage'
import NotFound from './pages/NotFound'
import AppShell from './components/layout/AppShell'
import { RequireAuth } from './components/layout/AppShell'
import DashboardPage from './pages/DashboardPage'
import HistoryPage from './pages/HistoryPage'
import NutritionPage from './pages/NutritionPage'
import ComparePage from './pages/ComparePage'
import MealPlannerPage from './pages/MealPlannerPage'
import { AllergensPage, BMIPage, ChemicalPage, ChatPage, ProfilePage, ReportsPage } from './pages/ToolPages'

function ScrollManager() {
  const { pathname, hash } = useLocation()
  useEffect(() => {
    if (hash) {
      const el = document.getElementById(hash.slice(1))
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' })
        return
      }
    }
    window.scrollTo({ top: 0 })
  }, [pathname, hash])
  return null
}

export default function App() {
  return (
    <AuthProvider>
      <ScrollManager />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/analyze" element={<AnalyzePage key="analyze" />} />
        <Route path="/signin" element={<AuthPage key="signin" mode="signin" />} />
        <Route path="/signup" element={<AuthPage key="signup" mode="signup" />} />
        <Route element={<AppShell />}>
          <Route path="/scan-packaged" element={<AnalyzePage key="packaged-analyze" initialMode="packaged" inShell />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/chemical" element={<ChemicalPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/bmi" element={<BMIPage />} />
          <Route path="/dashboard" element={<RequireAuth><DashboardPage /></RequireAuth>} />
          <Route path="/history" element={<RequireAuth><HistoryPage /></RequireAuth>} />
          <Route path="/nutrition" element={<RequireAuth><NutritionPage /></RequireAuth>} />
          <Route path="/meal-planner" element={<RequireAuth><MealPlannerPage /></RequireAuth>} />
          <Route path="/allergens" element={<RequireAuth><AllergensPage /></RequireAuth>} />
          <Route path="/reports" element={<RequireAuth><ReportsPage /></RequireAuth>} />
          <Route path="/profile" element={<RequireAuth><ProfilePage /></RequireAuth>} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AuthProvider>
  )
}