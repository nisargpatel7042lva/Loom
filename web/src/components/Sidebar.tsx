import { motion } from 'framer-motion'
import { Home, Brain, Search, Sparkles, Trash2, Layers, Database } from 'lucide-react'
import { cn } from '../lib/utils'
import { ApiDot } from './ui'

type Page = 'home' | 'remember' | 'recall' | 'improve' | 'forget'

const NAV = [
  {
    id: 'home' as Page,
    Icon: Home,
    label: 'Home',
    api: null,
    activeColor: 'text-white',
    indicatorColor: 'bg-white',
  },
  {
    id: 'remember' as Page,
    Icon: Database,
    label: 'Remember',
    api: 'cognee.add()',
    activeColor: 'text-emerald-400',
    indicatorColor: 'bg-emerald-400',
  },
  {
    id: 'recall' as Page,
    Icon: Search,
    label: 'Recall',
    api: 'cognee.search()',
    activeColor: 'text-amber-400',
    indicatorColor: 'bg-amber-400',
  },
  {
    id: 'improve' as Page,
    Icon: Sparkles,
    label: 'Improve',
    api: 'add_feedback()',
    activeColor: 'text-blue-400',
    indicatorColor: 'bg-blue-400',
  },
  {
    id: 'forget' as Page,
    Icon: Trash2,
    label: 'Forget',
    api: 'cognee.forget()',
    activeColor: 'text-rose-400',
    indicatorColor: 'bg-rose-400',
  },
]

export default function Sidebar({
  activePage,
  onNavigate,
  memoryCount,
  apiOnline,
}: {
  activePage: Page
  onNavigate: (p: Page) => void
  memoryCount: number
  apiOnline: boolean
}) {
  return (
    <aside className="fixed left-0 top-0 bottom-0 w-[220px] z-40 flex flex-col border-r border-white/[0.06] bg-black/60 backdrop-blur-xl">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-white/[0.06]">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-white/[0.06] border border-white/10 flex items-center justify-center">
            <Layers size={14} className="text-white/70" />
          </div>
          <div>
            <div className="text-white font-mono font-semibold text-sm leading-none">Loom</div>
            <div className="text-white/25 text-[10px] font-body mt-0.5">Memory Agent</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 px-3 flex flex-col gap-1">
        {NAV.map((item) => {
          const active = activePage === item.id
          return (
            <motion.button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              whileHover={{ x: 2 }}
              whileTap={{ scale: 0.98 }}
              className={cn(
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all duration-150 group',
                active
                  ? 'bg-white/[0.08] border border-white/[0.1]'
                  : 'hover:bg-white/[0.04] border border-transparent'
              )}
            >
              <item.Icon
                size={14}
                className={cn(
                  'flex-shrink-0 transition-colors',
                  active ? item.activeColor : 'text-white/30 group-hover:text-white/60'
                )}
              />
              <div className="min-w-0">
                <div
                  className={cn(
                    'text-[13px] font-body font-medium transition-colors',
                    active ? 'text-white' : 'text-white/40 group-hover:text-white/70'
                  )}
                >
                  {item.label}
                </div>
                {item.api && (
                  <div
                    className={cn(
                      'text-[9px] font-mono mt-0.5 transition-colors truncate',
                      active
                        ? `${item.activeColor} opacity-70`
                        : 'text-white/15 group-hover:text-white/25'
                    )}
                  >
                    {item.api}
                  </div>
                )}
              </div>
              {active && (
                <motion.div
                  layoutId="sidebar-indicator"
                  className={cn('ml-auto w-1 h-4 rounded-full', item.indicatorColor)}
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
            </motion.button>
          )
        })}
      </nav>

      {/* Bottom status */}
      <div className="border-t border-white/[0.06] px-5 py-4 space-y-3">
        <ApiDot online={apiOnline} />
        <div className="flex items-center justify-between">
          <span className="text-white/25 text-[10px] font-body">In memory</span>
          <span
            className={cn(
              'text-[10px] font-mono',
              memoryCount > 0 ? 'text-amber-400' : 'text-white/20'
            )}
          >
            {memoryCount} events
          </span>
        </div>
        <div className="text-white/10 text-[9px] font-mono">Cognee 1.2.1 · FastEmbed</div>
      </div>
    </aside>
  )
}
