import { motion } from 'framer-motion'
import { Database, Search, Sparkles, Trash2, Plus, Layers } from 'lucide-react'
import { BlurFade, NumberTicker } from './ui'

const LIFECYCLE = [
  {
    step: '01',
    name: 'Remember',
    Icon: Database,
    api: 'cognee.add()',
    llm: '0 LLM calls',
    color: 'text-emerald-400',
    border: 'border-emerald-500/20',
    bg: 'bg-emerald-500/5',
    desc: 'Ingest live Jupiter markets into vector memory. Local FastEmbed vectorization — no quota consumed.',
  },
  {
    step: '02',
    name: 'Recall',
    Icon: Search,
    api: 'cognee.search()',
    llm: '1 LLM call',
    color: 'text-amber-400',
    border: 'border-amber-500/20',
    bg: 'bg-amber-500/5',
    desc: 'Cosine similarity retrieves the 8 most analogous historical markets. One Gemini call synthesizes a trader brief.',
  },
  {
    step: '03',
    name: 'Improve',
    Icon: Sparkles,
    api: 'add_feedback()',
    llm: '0 LLM calls',
    color: 'text-blue-400',
    border: 'border-blue-500/20',
    bg: 'bg-blue-500/5',
    desc: 'Records actual outcomes and scores recall quality 1–5. Stored in Cognee SQLite session cache.',
  },
  {
    step: '04',
    name: 'Forget',
    Icon: Trash2,
    api: 'cognee.forget()',
    llm: '0 LLM calls',
    color: 'text-rose-400',
    border: 'border-rose-500/20',
    bg: 'bg-rose-500/5',
    desc: 'Detects chronic false-positive precedents and prunes them. Graph stays coherent — shared nodes are detagged, not removed.',
  },
]

const STATS = [
  { value: 3700, suffix: '+', label: 'Live Jupiter markets' },
  { value: 0, suffix: '', label: 'LLM calls at ingest' },
  { value: 1, suffix: '', label: 'LLM call per analysis' },
  { value: 20, suffix: '/day', label: 'Free-tier analyses' },
]

export default function DashboardPage({
  memoryCount,
  onNavigate,
}: {
  memoryCount: number
  onNavigate: (page: string) => void
}) {
  return (
    <BlurFade>
      {/* Hero */}
      <div className="mb-10">
        <motion.div
          initial={{ opacity: 0, y: 16, filter: 'blur(8px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        >
          <h1
            className="font-heading italic text-white leading-[0.9] tracking-[-0.02em] mb-4"
            style={{ fontSize: 'clamp(40px, 7vw, 80px)' }}
          >
            Stop predicting.
            <br />
            <span className="text-white/25">Start remembering.</span>
          </h1>
          <p className="text-white/40 text-base font-body font-light max-w-xl leading-relaxed">
            Loom is an experience engine for prediction markets. Every resolved outcome is
            stored in Cognee memory so the next structurally identical question benefits
            from everything that came before.
          </p>
        </motion.div>
      </div>

      {/* Memory status */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15, duration: 0.7 }}
        className="mb-8"
      >
        <div className="liquid-glass border border-white/[0.07] rounded-2xl p-5 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-full bg-amber-400/10 border border-amber-400/20 flex items-center justify-center">
              <Layers size={18} className="text-amber-400" />
            </div>
            <div>
              <div className="text-white text-2xl font-mono font-light">
                <NumberTicker value={memoryCount} />
              </div>
              <div className="text-white/30 text-xs font-body mt-0.5">events in Cognee memory</div>
            </div>
          </div>
          <button
            onClick={() => onNavigate('remember')}
            className="liquid-glass border border-amber-400/20 text-amber-400 text-xs font-mono px-4 py-2 rounded-full hover:bg-amber-400/10 transition-all flex items-center gap-2"
          >
            <Plus size={12} />
            {memoryCount === 0 ? 'Ingest first batch' : 'Ingest more'}
          </button>
        </div>
      </motion.div>

      {/* Lifecycle grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-10">
        {LIFECYCLE.map((item, i) => (
          <motion.button
            key={item.name}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.07, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            onClick={() => onNavigate(item.name.toLowerCase())}
            className={`liquid-glass border ${item.border} rounded-2xl p-5 text-left hover:scale-[1.02] transition-all duration-200 group`}
          >
            <div className="flex items-center justify-between mb-4">
              <span className="text-white/15 font-mono text-xs">{item.step}</span>
              <span
                className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${item.bg} border ${item.border} ${item.color}`}
              >
                {item.llm}
              </span>
            </div>
            <div className={`mb-1 ${item.color}`}>
              <item.Icon size={18} />
            </div>
            <h3 className={`font-heading italic text-2xl mb-1 ${item.color}`}>{item.name}</h3>
            <p className="text-white/30 text-[10px] font-mono mb-3">{item.api}</p>
            <p className="text-white/40 text-xs font-body leading-relaxed">{item.desc}</p>
            <div
              className={`mt-4 text-[10px] font-mono ${item.color} opacity-0 group-hover:opacity-60 transition-opacity`}
            >
              Open
            </div>
          </motion.button>
        ))}
      </div>

      {/* Stats row */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="grid grid-cols-2 sm:grid-cols-4 gap-4"
      >
        {STATS.map((s) => (
          <div
            key={s.label}
            className="liquid-glass border border-white/[0.06] rounded-xl p-5"
          >
            <div className="text-3xl font-mono font-light text-white mb-1.5">
              <NumberTicker value={s.value} />
              <span className="text-white/40">{s.suffix}</span>
            </div>
            <div className="text-white/25 text-xs font-body">{s.label}</div>
          </div>
        ))}
      </motion.div>

      {/* Architecture note */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6 }}
        className="mt-6 border border-white/[0.05] rounded-xl p-5"
      >
        <p className="text-white/20 text-[10px] font-mono tracking-widest uppercase mb-3">
          Architecture — 20 RPD free tier
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            { step: 'Ingest', code: 'cognee.add() + FastEmbed', note: '0 LLM calls — unlimited' },
            { step: 'Recall', code: 'cosine_similarity(query, store)', note: '0 LLM calls — instant' },
            { step: 'Analyze', code: 'litellm.acompletion(gemini)', note: '1 LLM call — 20/day free' },
          ].map((a) => (
            <div key={a.step} className="space-y-1.5">
              <div className="text-white/20 text-[10px] font-mono">{a.step}</div>
              <div className="text-amber-400/70 text-[11px] font-mono">{a.code}</div>
              <div className="text-white/25 text-[10px] font-body">{a.note}</div>
            </div>
          ))}
        </div>
      </motion.div>
    </BlurFade>
  )
}
