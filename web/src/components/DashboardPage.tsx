import { useRef, useState, useEffect } from 'react'
import { motion, useAnimationFrame } from 'framer-motion'
import {
  Database, Search, Sparkles, Trash2,
  ArrowRight, TrendingUp, TrendingDown, Minus,
  Layers, Zap,
} from 'lucide-react'
import { NumberTicker } from './ui'

// ── Static demo data (dashboard only — purely decorative) ─────────────────────

const DEMO_MARKETS = [
  {
    id: 'POLY-30615',
    question: 'Will the Federal Reserve cut rates at the June 2026 meeting?',
    category: 'Economics',
    prob: 0.62,
    trend: 'up' as const,
    brief: '7 analogous markets found. 5 resolved YES / 2 resolved NO. Strong easing bias — lean YES.',
  },
  {
    id: 'POLY-411239',
    question: 'Will Bitcoin exceed $120,000 before end of Q3 2026?',
    category: 'Crypto',
    prob: 0.41,
    trend: 'down' as const,
    brief: '5 analogous ATH markets. Historically resolve YES ~40% near cycle peaks — neutral lean.',
  },
  {
    id: 'POLY-424982',
    question: 'Will 2026 US midterm elections shift House control?',
    category: 'Politics',
    prob: 0.55,
    trend: 'neutral' as const,
    brief: '4 analogous midterm markets. Incumbent party historically loses seats — lean YES.',
  },
]

const TICKER_ITEMS = [
  { id: 'POLY-30615',  q: 'Will the Fed cut rates in June 2026?',            prob: 62 },
  { id: 'POLY-41123',  q: 'Will BTC exceed $120K before Q3 2026?',           prob: 41 },
  { id: 'POLY-42498',  q: 'Will 2026 US midterms shift House control?',       prob: 55 },
  { id: 'POLY-80763',  q: 'Will ETH flip BTC market cap in 2026?',           prob: 18 },
  { id: 'POLY-30829',  q: 'Will inflation stay above 3% through Q2?',         prob: 34 },
  { id: 'POLY-54827',  q: 'Will S&P 500 hit 6,500 before year end?',         prob: 71 },
  { id: 'POLY-41386',  q: 'Will Trump impose new tariffs on EU goods?',       prob: 48 },
  { id: 'POLY-64386',  q: 'Will the ECB cut rates at the July meeting?',      prob: 67 },
]

// ── Marquee strip ─────────────────────────────────────────────────────────────

function MarqueeStrip() {
  const items = [...TICKER_ITEMS, ...TICKER_ITEMS]
  const ref = useRef<HTMLDivElement>(null)
  const xRef = useRef(0)

  useAnimationFrame((_, delta) => {
    xRef.current -= delta * 0.035
    const total = TICKER_ITEMS.length * 260
    if (Math.abs(xRef.current) >= total) xRef.current += total
    if (ref.current) ref.current.style.transform = `translateX(${xRef.current}px)`
  })

  return (
    <div className="relative w-full overflow-hidden py-3 border-y border-white/[0.05]">
      <div className="absolute left-0 top-0 bottom-0 w-20 z-10 pointer-events-none"
        style={{ background: 'linear-gradient(90deg, #000 0%, transparent 100%)' }} />
      <div className="absolute right-0 top-0 bottom-0 w-20 z-10 pointer-events-none"
        style={{ background: 'linear-gradient(270deg, #000 0%, transparent 100%)' }} />
      <div ref={ref} className="flex gap-0 will-change-transform" style={{ width: 'max-content' }}>
        {items.map((item, i) => {
          const color = item.prob >= 60 ? 'text-emerald-400' : item.prob >= 40 ? 'text-amber-400' : 'text-rose-400'
          return (
            <div key={i} className="flex items-center gap-3 px-6 py-1 border-r border-white/[0.04]" style={{ width: 260 }}>
              <span className="text-white/15 text-[9px] font-mono flex-shrink-0">{item.id}</span>
              <span className="text-white/40 text-[11px] font-body truncate flex-1">{item.q}</span>
              <span className={`text-[10px] font-mono flex-shrink-0 ${color}`}>{item.prob}%</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Probability ring ──────────────────────────────────────────────────────────

function ProbRing({ p, active }: { p: number; active: boolean }) {
  const r = 18, circ = 2 * Math.PI * r, dash = circ * p
  const color = p >= 0.6 ? '#34d399' : p >= 0.4 ? '#fbbf24' : '#f87171'
  return (
    <div className="relative w-12 h-12 flex items-center justify-center flex-shrink-0">
      <svg width="48" height="48" className="-rotate-90">
        <circle cx="24" cy="24" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="2.5" />
        <motion.circle cx="24" cy="24" r={r} fill="none" stroke={color} strokeWidth="2.5"
          strokeLinecap="round" strokeDasharray={circ}
          animate={{ strokeDashoffset: active ? circ - dash : circ }}
          transition={{ duration: 0.9, ease: 'easeOut' }}
        />
      </svg>
      <span className="absolute text-[10px] font-mono" style={{ color }}>
        {Math.round(p * 100)}
      </span>
    </div>
  )
}

function TrendIcon({ t }: { t: 'up' | 'down' | 'neutral' }) {
  if (t === 'up') return <TrendingUp size={10} className="text-emerald-400" />
  if (t === 'down') return <TrendingDown size={10} className="text-rose-400" />
  return <Minus size={10} className="text-white/20" />
}

// ── Terminal window ───────────────────────────────────────────────────────────

function TerminalWindow({ memoryCount }: { memoryCount: number }) {
  const [activeCard, setActiveCard] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setActiveCard((c) => (c + 1) % DEMO_MARKETS.length), 3400)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="relative w-full">
      <div className="absolute -inset-px rounded-2xl pointer-events-none"
        style={{ background: 'linear-gradient(135deg, rgba(251,191,36,0.15) 0%, rgba(139,92,246,0.10) 50%, rgba(251,191,36,0.05) 100%)', filter: 'blur(1px)' }} />

      {/* Border beam */}
      <div className="absolute inset-0 rounded-2xl overflow-hidden pointer-events-none">
        <motion.div className="absolute h-[2px] w-40 opacity-70"
          style={{ background: 'linear-gradient(90deg, transparent, rgba(251,191,36,0.9), transparent)', top: 0 }}
          animate={{ left: ['-30%', '130%'] }}
          transition={{ duration: 2.2, repeat: Infinity, ease: 'linear', repeatDelay: 1.2 }}
        />
        <motion.div className="absolute w-[2px] h-32 opacity-50"
          style={{ background: 'linear-gradient(180deg, transparent, rgba(139,92,246,0.7), transparent)', right: 0 }}
          animate={{ top: ['-20%', '120%'] }}
          transition={{ duration: 2.8, repeat: Infinity, ease: 'linear', repeatDelay: 0.8, delay: 1.1 }}
        />
      </div>

      <div className="relative liquid-glass rounded-2xl border border-white/[0.08] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/[0.06] bg-white/[0.02]">
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-rose-500/60" />
            <div className="w-2.5 h-2.5 rounded-full bg-amber-400/60" />
            <div className="w-2.5 h-2.5 rounded-full bg-emerald-400/60" />
          </div>
          <span className="text-white/25 text-[10px] font-mono tracking-widest">LOOM — MEMORY RECALL</span>
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" style={{ animation: 'pulse 2s infinite' }} />
            <span className="text-emerald-400/60 text-[9px] font-mono">DEMO</span>
          </div>
        </div>

        {/* Memory count bar */}
        <div className="flex items-center gap-3 px-5 py-2.5 border-b border-white/[0.04] bg-white/[0.01]">
          <Database size={10} className="text-amber-400/60 flex-shrink-0" />
          <span className="text-white/30 text-[10px] font-mono">
            memory:{' '}
            <span className="text-amber-400">
              {memoryCount > 0 ? `${memoryCount} events indexed` : 'empty — ingest via Remember'}
            </span>
          </span>
          <div className="flex-1 h-px bg-white/[0.04]" />
          <span className="text-white/20 text-[9px] font-mono">FastEmbed · bge-small-en-v1.5</span>
        </div>

        {/* Demo market cards */}
        {DEMO_MARKETS.map((market, i) => (
          <motion.div key={market.id}
            animate={{ opacity: activeCard === i ? 1 : 0.3, backgroundColor: activeCard === i ? 'rgba(255,255,255,0.025)' : 'transparent' }}
            transition={{ duration: 0.35 }}
            className="border-b border-white/[0.04] last:border-0 p-4 cursor-pointer"
            onClick={() => setActiveCard(i)}
          >
            <div className="flex items-start gap-3">
              <ProbRing p={market.prob} active={activeCard === i} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                  <span className="text-white/25 text-[9px] font-mono">{market.id}</span>
                  <span className="text-white/15 text-[9px] font-mono border border-white/[0.08] rounded-full px-2 py-px">
                    {market.category}
                  </span>
                  <TrendIcon t={market.trend} />
                </div>
                <p className="text-white/75 text-sm font-body leading-snug mb-2">{market.question}</p>
                <motion.div
                  animate={{ height: activeCard === i ? 'auto' : 0, opacity: activeCard === i ? 1 : 0 }}
                  transition={{ duration: 0.3 }}
                  style={{ overflow: 'hidden' }}
                >
                  <p className="text-white/40 text-[11px] font-body leading-relaxed border-l-2 border-amber-400/25 pl-3">
                    {market.brief}
                  </p>
                </motion.div>
              </div>
            </div>
          </motion.div>
        ))}

        {/* Shimmer bottom */}
        <div className="relative h-px overflow-hidden">
          <div className="absolute inset-0 bg-white/[0.04]" />
          <motion.div className="absolute top-0 h-full w-28 rounded-full"
            style={{ background: 'linear-gradient(90deg, transparent, rgba(251,191,36,0.7), transparent)' }}
            animate={{ left: ['-15%', '115%'] }}
            transition={{ duration: 2.8, repeat: Infinity, ease: 'linear', repeatDelay: 0.6 }}
          />
        </div>
      </div>
    </div>
  )
}

// ── Lifecycle cards ───────────────────────────────────────────────────────────

const LIFECYCLE = [
  {
    step: '01', name: 'Remember', Icon: Database, api: 'cognee.add()',
    llm: '0 LLM calls', color: 'text-emerald-400', border: 'border-emerald-500/20',
    bg: 'bg-emerald-500/5', glow: 'rgba(52,211,153,0.06)',
    desc: 'Ingest live Jupiter markets into vector memory. Local FastEmbed vectorization — no quota consumed.',
  },
  {
    step: '02', name: 'Recall', Icon: Search, api: 'cognee.search()',
    llm: '1 LLM call', color: 'text-amber-400', border: 'border-amber-500/20',
    bg: 'bg-amber-500/5', glow: 'rgba(251,191,36,0.06)',
    desc: 'Cosine similarity retrieves the 8 most analogous historical markets. One Gemini call synthesizes a brief.',
  },
  {
    step: '03', name: 'Improve', Icon: Sparkles, api: 'add_feedback()',
    llm: '0 LLM calls', color: 'text-blue-400', border: 'border-blue-500/20',
    bg: 'bg-blue-500/5', glow: 'rgba(96,165,250,0.06)',
    desc: 'Records actual outcomes and scores recall quality 1–5. Stored in Cognee SQLite session cache.',
  },
  {
    step: '04', name: 'Forget', Icon: Trash2, api: 'cognee.forget()',
    llm: '0 LLM calls', color: 'text-rose-400', border: 'border-rose-500/20',
    bg: 'bg-rose-500/5', glow: 'rgba(251,113,133,0.06)',
    desc: 'Detects chronic false-positive precedents and prunes them from the knowledge graph.',
  },
]

// ── Main export ───────────────────────────────────────────────────────────────

export default function DashboardPage({
  memoryCount,
  onNavigate,
}: {
  memoryCount: number
  onNavigate: (page: string) => void
}) {

  return (
    <div className="-mx-6 md:-mx-8 -mt-8">

      {/* ═══ HERO ═══════════════════════════════════════════════════════════ */}
      <section className="relative min-h-[calc(100vh-56px)] flex flex-col overflow-hidden">

        {/* Aurora background */}
        <div className="absolute inset-0 pointer-events-none">
          <motion.div className="absolute rounded-full"
            style={{ width: 700, height: 700, top: '-15%', left: '-15%',
              background: 'radial-gradient(circle, rgba(251,191,36,0.12) 0%, transparent 65%)', filter: 'blur(50px)' }}
            animate={{ x: [0, 50, 0], y: [0, -40, 0], scale: [1, 1.12, 1] }}
            transition={{ duration: 16, repeat: Infinity, ease: 'easeInOut' }}
          />
          <motion.div className="absolute rounded-full"
            style={{ width: 800, height: 600, top: '25%', right: '-20%',
              background: 'radial-gradient(circle, rgba(139,92,246,0.09) 0%, transparent 65%)', filter: 'blur(70px)' }}
            animate={{ x: [0, -60, 0], y: [0, 50, 0], scale: [1, 1.08, 1] }}
            transition={{ duration: 20, repeat: Infinity, ease: 'easeInOut', delay: 2 }}
          />
          <motion.div className="absolute rounded-full"
            style={{ width: 500, height: 500, bottom: '0%', left: '35%',
              background: 'radial-gradient(circle, rgba(52,211,153,0.06) 0%, transparent 65%)', filter: 'blur(60px)' }}
            animate={{ x: [0, 30, -20, 0], y: [0, -30, 10, 0] }}
            transition={{ duration: 22, repeat: Infinity, ease: 'easeInOut', delay: 4 }}
          />
          <div className="absolute inset-0"
            style={{ backgroundImage: 'radial-gradient(rgba(255,255,255,0.07) 1px, transparent 1px)', backgroundSize: '32px 32px' }} />
          <div className="absolute inset-0"
            style={{ background: 'radial-gradient(ellipse 85% 70% at 50% 40%, transparent 35%, rgba(0,0,0,0.75) 100%)' }} />
        </div>

        {/* ── Split layout ── */}
        <div className="relative z-10 flex-1 grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-8 items-center px-6 md:px-8 pt-12 pb-8 max-w-7xl mx-auto w-full">

          {/* LEFT — copy */}
          <div className="flex flex-col">
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
              className="inline-flex items-center gap-2.5 self-start rounded-full border border-white/10 bg-white/[0.04] backdrop-blur-sm px-4 py-1.5 mb-8"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" style={{ animation: 'pulse 2s infinite' }} />
              <span className="text-white/45 text-[10px] font-mono tracking-widest uppercase">
                Live · Jupiter API · Cognee 1.2.1
              </span>
            </motion.div>

            <motion.h1
              initial={{ opacity: 0, y: 28, filter: 'blur(12px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              transition={{ duration: 1, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
              className="font-heading italic leading-[0.9] tracking-[-0.03em] mb-6"
              style={{ fontSize: 'clamp(44px, 6vw, 88px)' }}
            >
              <span style={{
                background: 'linear-gradient(160deg, #ffffff 0%, #ffffff 50%, rgba(255,255,255,0.45) 100%)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text',
              }}>
                Stop<br />predicting.
              </span>
              <br />
              <span style={{
                background: 'linear-gradient(135deg, #fbbf24 0%, #f59e0b 45%, #c084fc 100%)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text',
              }}>
                Start<br />remembering.
              </span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.35 }}
              className="text-white/40 text-base max-w-md leading-relaxed font-body font-light mb-10"
            >
              Loom learns from every resolved prediction market. When the same question opens again, it already knows what happened last time — and why.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, delay: 0.5 }}
              className="flex items-center gap-3 flex-wrap mb-12"
            >
              <button onClick={() => onNavigate('remember')}
                className="flex items-center gap-2 bg-white text-black text-[13px] font-semibold px-7 py-3 rounded-full hover:bg-white/90 transition-all hover:scale-105 active:scale-95 font-body">
                Get started
                <ArrowRight size={14} />
              </button>
              <button onClick={() => onNavigate('recall')}
                className="flex items-center gap-2 liquid-glass border border-white/12 text-white/60 hover:text-white text-[13px] font-medium px-7 py-3 rounded-full transition-all font-body">
                Try recall
              </button>
            </motion.div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.75 }}
              className="flex items-center gap-8 flex-wrap"
            >
              {[
                { v: String(memoryCount), l: 'events in memory', live: true },
                { v: '0', l: 'LLM calls at ingest', live: false },
                { v: '1', l: 'LLM per analysis', live: false },
              ].map((s) => (
                <div key={s.l}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-white text-2xl font-mono font-light">{s.v}</span>
                    {s.live && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" style={{ animation: 'pulse 2s infinite' }} />}
                  </div>
                  <div className="text-white/25 text-[10px] font-body mt-0.5">{s.l}</div>
                </div>
              ))}
            </motion.div>
          </div>

          {/* RIGHT — terminal */}
          <motion.div
            initial={{ opacity: 0, x: 40, filter: 'blur(8px)' }}
            animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
            transition={{ duration: 1, delay: 0.4, ease: [0.16, 1, 0.3, 1] }}
          >
            <TerminalWindow memoryCount={memoryCount} />
          </motion.div>
        </div>

        {/* ── Marquee strip ── */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.0 }}
          className="relative z-10"
        >
          <MarqueeStrip />
        </motion.div>

        {/* ── Stats bar ── */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.1 }}
          className="relative z-10 grid grid-cols-2 sm:grid-cols-4 divide-x divide-white/[0.05] border-t border-white/[0.05]"
        >
          {[
            { value: 3700, suffix: '+', label: 'Jupiter live markets' },
            { value: 0,    suffix: '',  label: 'LLM calls at ingest' },
            { value: 1,    suffix: '',  label: 'LLM call per analysis' },
            { value: 20,   suffix: '/day', label: 'Free-tier analyses' },
          ].map((s) => (
            <div key={s.label} className="bg-black/50 px-6 py-5 text-center">
              <div className="text-2xl sm:text-3xl font-mono font-light text-white mb-1">
                <NumberTicker value={s.value} />
                <span className="text-white/35">{s.suffix}</span>
              </div>
              <div className="text-white/25 text-xs font-body">{s.label}</div>
            </div>
          ))}
        </motion.div>
      </section>

      {/* ═══ LIFECYCLE ══════════════════════════════════════════════════════ */}
      <section className="px-6 md:px-8 py-16 md:py-20">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.7 }}
          className="mb-12"
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="h-px flex-1 max-w-[48px] bg-white/10" />
            <p className="text-white/25 text-[10px] font-mono tracking-[0.3em] uppercase">Cognee Memory Lifecycle</p>
          </div>
          <h2 className="font-heading italic text-white leading-[0.93] tracking-[-0.02em]"
            style={{ fontSize: 'clamp(32px, 5vw, 60px)' }}>
            Four steps.{' '}
            <span className="text-white/25">Zero wasted calls.</span>
          </h2>
        </motion.div>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {LIFECYCLE.map((item, i) => (
            <motion.button key={item.name}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.2 }}
              transition={{ delay: i * 0.09, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
              whileHover={{ y: -3, transition: { duration: 0.2 } }}
              onClick={() => onNavigate(item.name.toLowerCase())}
              className={`liquid-glass border ${item.border} rounded-2xl p-5 text-left transition-colors duration-300 group relative overflow-hidden`}
              style={{ boxShadow: `0 0 40px ${item.glow}` }}
            >
              <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
                style={{ background: `radial-gradient(ellipse at 50% 0%, ${item.glow.replace('0.06', '0.14')} 0%, transparent 70%)` }} />
              <div className="relative z-10">
                <div className="flex items-center justify-between mb-5">
                  <span className="text-white/12 font-mono text-xs">{item.step}</span>
                  <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${item.bg} border ${item.border} ${item.color}`}>
                    {item.llm}
                  </span>
                </div>
                <div className={`mb-2.5 ${item.color}`}><item.Icon size={18} /></div>
                <h3 className={`font-heading italic text-2xl mb-1 ${item.color}`}>{item.name}</h3>
                <p className="text-white/20 text-[10px] font-mono mb-3">{item.api}</p>
                <p className="text-white/38 text-xs font-body leading-relaxed">{item.desc}</p>
                <div className={`mt-4 text-[10px] font-mono ${item.color} opacity-0 group-hover:opacity-50 transition-opacity flex items-center gap-1`}>
                  Open <ArrowRight size={10} />
                </div>
              </div>
            </motion.button>
          ))}
        </div>
      </section>

      {/* ═══ ARCHITECTURE ═══════════════════════════════════════════════════ */}
      <section className="px-6 md:px-8 pb-20 border-t border-white/[0.05]">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.3 }}
          transition={{ duration: 0.7 }}
          className="pt-14 mb-10"
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="h-px flex-1 max-w-[48px] bg-white/10" />
            <p className="text-white/25 text-[10px] font-mono tracking-[0.3em] uppercase">Architecture · 20 RPD free tier</p>
          </div>
          <h2 className="font-heading italic text-white leading-[0.93] tracking-[-0.02em]"
            style={{ fontSize: 'clamp(28px, 4vw, 52px)' }}>
            One question.{' '}
            <span className="text-white/25">Three API calls.</span>
          </h2>
        </motion.div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            {
              n: '1', title: 'Fetch live data', Icon: Layers,
              code: 'get_events(category="economics", max_events=50)',
              note: 'Jupiter Prediction API · 3,700+ active markets · no auth required',
              accent: 'border-white/[0.06]',
            },
            {
              n: '2', title: 'Recall from memory', Icon: Search,
              code: 'cognee.search(query, SearchType.CHUNKS)',
              note: 'FastEmbed cosine similarity · local · 0 LLM calls · instant',
              accent: 'border-amber-500/20',
            },
            {
              n: '3', title: 'Synthesize brief', Icon: Zap,
              code: 'litellm.acompletion(model, messages)',
              note: 'Gemini 2.5 Flash · exactly 1 call · 20 analyses per day free',
              accent: 'border-white/[0.06]',
            },
          ].map((a, i) => (
            <motion.div key={a.n}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, amount: 0.3 }}
              transition={{ delay: i * 0.1, duration: 0.6 }}
              className={`liquid-glass border ${a.accent} rounded-2xl p-5 space-y-4`}
            >
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center flex-shrink-0">
                  <a.Icon size={13} className="text-white/40" />
                </div>
                <span className="text-white/65 text-sm font-body font-medium">{a.title}</span>
              </div>
              <code className="block text-amber-400/75 text-[11px] font-mono leading-relaxed break-all">
                {a.code}
              </code>
              <p className="text-white/28 text-[11px] font-body leading-relaxed">{a.note}</p>
            </motion.div>
          ))}
        </div>
      </section>
    </div>
  )
}
