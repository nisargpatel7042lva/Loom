import { useState, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Layers, Menu } from 'lucide-react'
import { api } from './lib/api'
import Sidebar from './components/Sidebar'
import DashboardPage from './components/DashboardPage'
import RememberPage from './components/RememberPage'
import RecallPage from './components/RecallPage'
import ImprovePage from './components/ImprovePage'
import ForgetPage from './components/ForgetPage'
import { Toaster } from './components/ui'

type Page = 'home' | 'remember' | 'recall' | 'improve' | 'forget'

const PAGE_TITLES: Record<Page, string> = {
  home: 'Overview',
  remember: 'Remember',
  recall: 'Recall & Analyze',
  improve: 'Improve',
  forget: 'Forget',
}

export default function App() {
  const [page, setPage] = useState<Page>('home')
  const [memoryCount, setMemoryCount] = useState(0)
  const [apiOnline, setApiOnline] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)

  const refreshStatus = () => {
    api.status()
      .then((s) => {
        setApiOnline(true)
        setMemoryCount(s.events_in_memory)
      })
      .catch(() => {
        setApiOnline(false)
      })
  }

  useEffect(() => {
    refreshStatus()
    const id = setInterval(refreshStatus, 15_000)
    return () => clearInterval(id)
  }, [])

  const navigate = (p: string) => {
    setPage(p as Page)
    setMobileSidebarOpen(false)
  }

  return (
    <div className="bg-black min-h-screen text-white grain">
      {/* Background ambient glows */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute top-0 left-[220px] w-[500px] h-[400px]"
          style={{
            background:
              'radial-gradient(ellipse at 30% 20%, rgba(245,158,11,0.03) 0%, transparent 60%)',
          }}
        />
        <div
          className="absolute bottom-0 right-0 w-[600px] h-[400px]"
          style={{
            background:
              'radial-gradient(ellipse at 70% 80%, rgba(139,92,246,0.025) 0%, transparent 60%)',
          }}
        />
      </div>

      {/* Desktop sidebar */}
      <div className="hidden md:block">
        <Sidebar
          activePage={page}
          onNavigate={(p) => navigate(p)}
          memoryCount={memoryCount}
          apiOnline={apiOnline}
        />
      </div>

      {/* Mobile header */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-40 border-b border-white/[0.06] bg-black/80 backdrop-blur-xl px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers size={14} className="text-white/60" />
          <span className="text-white font-mono font-semibold text-sm">Loom</span>
        </div>
        <button
          onClick={() => setMobileSidebarOpen((o) => !o)}
          className="w-8 h-8 flex items-center justify-center text-white/50 hover:text-white transition-colors"
        >
          <Menu size={16} />
        </button>
      </div>

      {/* Mobile sidebar overlay */}
      <AnimatePresence>
        {mobileSidebarOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="md:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
              onClick={() => setMobileSidebarOpen(false)}
            />
            <motion.div
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 400, damping: 40 }}
              className="md:hidden fixed left-0 top-0 bottom-0 z-50 w-[220px]"
            >
              <Sidebar
                activePage={page}
                onNavigate={(p) => navigate(p)}
                memoryCount={memoryCount}
                apiOnline={apiOnline}
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Main content */}
      <main className="md:pl-[220px] pt-16 md:pt-0 min-h-screen">
        {/* API offline banner */}
        <AnimatePresence>
          {!apiOnline && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="border-b border-rose-500/20 bg-rose-500/5 px-6 py-2.5 flex items-center gap-3"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
              <span className="text-rose-400/80 text-xs font-mono">
                Backend offline — start the API server:
              </span>
              <span className="text-rose-400 text-xs font-mono bg-rose-500/10 px-2 py-0.5 rounded">
                uvicorn api.main:app --reload --port 8000
              </span>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Page header */}
        <div className="border-b border-white/[0.05] px-6 md:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-white/80 text-sm font-body font-medium">
              {PAGE_TITLES[page]}
            </h1>
            <span className="text-white/15">/</span>
            <span className="text-white/25 text-xs font-mono">Loom</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-white/25 text-[10px] font-mono hidden sm:block">
              Cognee 1.2.1 · FastEmbed · Gemini
            </span>
            <div
              className={`w-1.5 h-1.5 rounded-full ${apiOnline ? 'bg-emerald-400' : 'bg-rose-500'}`}
              style={apiOnline ? { animation: 'pulse 2s infinite' } : {}}
            />
          </div>
        </div>

        {/* Page body */}
        <div className="px-6 md:px-8 py-8">
          <AnimatePresence mode="wait">
            <motion.div
              key={page}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            >
              {page === 'home' && (
                <DashboardPage
                  memoryCount={memoryCount}
                  onNavigate={navigate}
                />
              )}
              {page === 'remember' && (
                <RememberPage onMemoryUpdate={refreshStatus} onNavigate={navigate} />
              )}
              {page === 'recall' && (
                <RecallPage memoryCount={memoryCount} onNavigate={navigate} />
              )}
              {page === 'improve' && <ImprovePage onNavigate={navigate} />}
              {page === 'forget' && <ForgetPage />}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      <Toaster />
    </div>
  )
}
