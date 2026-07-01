/**
 * Shared UI primitives — glass cards, buttons, badges, inputs, selects.
 * Design: MagicUI / shadcn patterns on pure-black bg with amber accents.
 */

import { cn } from '../lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
import { useEffect, useRef, useState, type ReactNode } from 'react'

// ── Card ─────────────────────────────────────────────────────────────────────

export function Card({
  children,
  className,
  glow,
}: {
  children: ReactNode
  className?: string
  glow?: 'amber' | 'blue' | 'green' | 'rose'
}) {
  const glowMap = {
    amber: 'shadow-[0_0_40px_rgba(251,191,36,0.07)]',
    blue: 'shadow-[0_0_40px_rgba(59,130,246,0.07)]',
    green: 'shadow-[0_0_40px_rgba(52,211,153,0.07)]',
    rose: 'shadow-[0_0_40px_rgba(251,113,133,0.07)]',
  }
  return (
    <div
      className={cn(
        'liquid-glass rounded-2xl border border-white/[0.07] relative overflow-hidden',
        glow && glowMap[glow],
        className
      )}
    >
      {children}
    </div>
  )
}

// BorderBeam — MagicUI pattern: animated gradient border orbiting a card
export function BorderBeam({ className }: { className?: string }) {
  return (
    <div
      className={cn('pointer-events-none absolute inset-0 rounded-[inherit]', className)}
      style={{ zIndex: 0 }}
    >
      <div
        className="absolute h-[2px] w-24 opacity-80"
        style={{
          background:
            'linear-gradient(90deg, transparent, rgba(251,191,36,0.8), transparent)',
          animation: 'beam-orbit 3s linear infinite',
          top: 0,
          left: '-100%',
        }}
      />
    </div>
  )
}

// ── Button ───────────────────────────────────────────────────────────────────

type ButtonVariant = 'primary' | 'ghost' | 'outline' | 'danger'

export function Button({
  children,
  onClick,
  disabled,
  loading,
  variant = 'primary',
  className,
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  loading?: boolean
  variant?: ButtonVariant
  className?: string
  type?: 'button' | 'submit'
}) {
  const base =
    'relative flex items-center justify-center gap-2 rounded-full text-[13px] font-semibold px-5 py-2.5 transition-all duration-200 active:scale-95 font-body select-none'

  const variants: Record<ButtonVariant, string> = {
    primary:
      'bg-white text-black hover:bg-white/90 disabled:opacity-40 disabled:cursor-not-allowed',
    ghost:
      'text-white/60 hover:text-white hover:bg-white/[0.06] disabled:opacity-40 disabled:cursor-not-allowed',
    outline:
      'border border-white/15 text-white/70 hover:border-white/30 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed',
    danger:
      'border border-rose-500/30 text-rose-400 hover:bg-rose-500/10 disabled:opacity-40 disabled:cursor-not-allowed',
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(base, variants[variant], className)}
    >
      {loading && <Spinner size="sm" />}
      {children}
    </button>
  )
}

// ── Input ────────────────────────────────────────────────────────────────────

export function Input({
  value,
  onChange,
  placeholder,
  className,
  label,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
  label?: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-white/40 text-xs font-mono tracking-wide">{label}</label>}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={cn(
          'bg-white/[0.04] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/20',
          'focus:outline-none focus:border-amber-400/40 focus:bg-white/[0.06] transition-all',
          'font-body',
          className
        )}
      />
    </div>
  )
}

// ── Textarea ─────────────────────────────────────────────────────────────────

export function Textarea({
  value,
  onChange,
  placeholder,
  label,
  rows = 3,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  label?: string
  rows?: number
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-white/40 text-xs font-mono tracking-wide">{label}</label>}
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        className={cn(
          'bg-white/[0.04] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/20',
          'focus:outline-none focus:border-amber-400/40 transition-all resize-none',
          'font-body'
        )}
      />
    </div>
  )
}

// ── Select ───────────────────────────────────────────────────────────────────

export function Select({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  label?: string
  className?: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-white/40 text-xs font-mono tracking-wide">{label}</label>}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          'bg-[#0d0d0d] border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white',
          'focus:outline-none focus:border-amber-400/40 transition-all',
          'font-body appearance-none cursor-pointer',
          className
        )}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-[#0d0d0d]">
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}

// ── Slider ───────────────────────────────────────────────────────────────────

export function Slider({
  value,
  onChange,
  min,
  max,
  label,
  showValue = true,
}: {
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  label?: string
  showValue?: boolean
}) {
  const pct = ((value - min) / (max - min)) * 100

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        {label && <label className="text-white/40 text-xs font-mono tracking-wide">{label}</label>}
        {showValue && (
          <span className="text-amber-400 text-xs font-mono">{value}</span>
        )}
      </div>
      <div className="relative h-1.5 bg-white/10 rounded-full">
        <div
          className="absolute left-0 top-0 h-full bg-amber-400 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
        <input
          type="range"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="absolute inset-0 w-full opacity-0 cursor-pointer h-full"
        />
      </div>
    </div>
  )
}

// ── Toggle ───────────────────────────────────────────────────────────────────

export function Toggle({
  value,
  onChange,
  label,
}: {
  value: boolean
  onChange: (v: boolean) => void
  label?: string
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={value}
        onClick={() => onChange(!value)}
        className={cn(
          'relative w-10 h-5 rounded-full transition-all duration-200',
          value ? 'bg-amber-400' : 'bg-white/10'
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 w-4 h-4 bg-black rounded-full transition-all duration-200',
            value ? 'left-[calc(100%-18px)]' : 'left-0.5'
          )}
        />
      </button>
      {label && <span className="text-white/60 text-sm font-body">{label}</span>}
    </div>
  )
}

// ── Badge ────────────────────────────────────────────────────────────────────

type BadgeColor = 'amber' | 'green' | 'rose' | 'blue' | 'white'

export function Badge({ children, color = 'white' }: { children: ReactNode; color?: BadgeColor }) {
  const colors: Record<BadgeColor, string> = {
    amber: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
    green: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
    rose: 'text-rose-400 bg-rose-400/10 border-rose-400/20',
    blue: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
    white: 'text-white/50 bg-white/5 border-white/10',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-mono border',
        colors[color]
      )}
    >
      {children}
    </span>
  )
}

// ── Spinner ──────────────────────────────────────────────────────────────────

export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizes = { sm: 'w-3 h-3 border', md: 'w-5 h-5 border-2', lg: 'w-8 h-8 border-2' }
  return (
    <div
      className={cn('rounded-full border-white/20 border-t-white animate-spin', sizes[size])}
    />
  )
}

// ── BlurFade — MagicUI pattern ───────────────────────────────────────────────

export function BlurFade({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode
  delay?: number
  className?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16, filter: 'blur(8px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{ duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ── NumberTicker — MagicUI pattern ──────────────────────────────────────────

export function NumberTicker({
  value,
  duration = 1,
  className,
}: {
  value: number
  duration?: number
  className?: string
}) {
  const [display, setDisplay] = useState(0)
  const startRef = useRef<number | null>(null)

  useEffect(() => {
    startRef.current = null
    const target = value
    const step = (ts: number) => {
      if (!startRef.current) startRef.current = ts
      const progress = Math.min((ts - startRef.current) / (duration * 1000), 1)
      const eased = 1 - Math.pow(1 - progress, 4)
      setDisplay(Math.round(eased * target))
      if (progress < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [value, duration])

  return <span className={className}>{display.toLocaleString()}</span>
}

// ── Toast ────────────────────────────────────────────────────────────────────

export type ToastType = 'success' | 'error' | 'info'

interface Toast {
  id: number
  message: string
  type: ToastType
}

let _toastId = 0
let _dispatch: ((t: Toast) => void) | null = null

export function toast(message: string, type: ToastType = 'info') {
  _dispatch?.({ id: ++_toastId, message, type })
}

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    _dispatch = (t) => {
      setToasts((prev) => [...prev, t])
      setTimeout(
        () => setToasts((prev) => prev.filter((x) => x.id !== t.id)),
        3500
      )
    }
    return () => { _dispatch = null }
  }, [])

  const colors: Record<ToastType, string> = {
    success: 'border-emerald-500/30 text-emerald-400',
    error: 'border-rose-500/30 text-rose-400',
    info: 'border-amber-500/30 text-amber-400',
  }

  return (
    <div className="fixed bottom-6 right-6 z-[999] flex flex-col gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.95 }}
            transition={{ duration: 0.3 }}
            className={cn(
              'liquid-glass border rounded-xl px-4 py-3 text-sm font-body max-w-sm',
              colors[t.type]
            )}
          >
            {t.message}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}

// ── SectionHeader ─────────────────────────────────────────────────────────────

export function SectionHeader({
  title,
  api,
  desc,
  llmCalls,
}: {
  title: string
  api: string
  desc: string
  llmCalls: number
}) {
  return (
    <div className="mb-8">
      <div className="flex items-center gap-3 mb-2 flex-wrap">
        <h1 className="font-heading italic text-white text-3xl leading-none">{title}</h1>
        <span className="code-pill">{api}</span>
        <Badge color={llmCalls === 0 ? 'green' : 'amber'}>
          {llmCalls} LLM call{llmCalls !== 1 ? 's' : ''}
        </Badge>
      </div>
      <p className="text-white/40 text-sm font-body leading-relaxed max-w-xl">{desc}</p>
    </div>
  )
}

// ── ChunkCard ─────────────────────────────────────────────────────────────────

export function ChunkCard({ text, index }: { text: string; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const preview = text.length > 220 ? text.slice(0, 220) + '…' : text

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06 }}
      className="liquid-glass border border-white/[0.06] rounded-xl p-4 cursor-pointer hover:border-white/15 transition-all"
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-start gap-3">
        <span className="text-white/20 font-mono text-xs mt-0.5 flex-shrink-0 w-4">
          {index + 1}
        </span>
        <p className="text-white/60 text-xs leading-relaxed font-body">
          {expanded ? text : preview}
        </p>
      </div>
      {text.length > 220 && (
        <p className="text-amber-400/50 text-[10px] font-mono mt-2 ml-7">
          {expanded ? '↑ collapse' : '↓ show all'}
        </p>
      )}
    </motion.div>
  )
}

// ── BriefCard ─────────────────────────────────────────────────────────────────

export function BriefCard({ brief }: { brief: string }) {
  return (
    <div className="liquid-glass-strong border border-amber-500/20 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
        <span className="text-amber-400/70 text-[10px] font-mono tracking-widest uppercase">
          Synthesis Brief
        </span>
      </div>
      <p className="text-white/85 text-sm leading-relaxed font-body">{brief}</p>
    </div>
  )
}

// ── Empty ──────────────────────────────────────────────────────────────────────

export function Empty({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      <div className="w-10 h-10 rounded-full border border-white/10 flex items-center justify-center">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1.5">
          <circle cx="12" cy="12" r="10"/>
          <path d="M8 12h8M12 8v8" strokeLinecap="round"/>
        </svg>
      </div>
      <p className="text-white/25 text-sm font-body text-center max-w-xs">{message}</p>
    </div>
  )
}

// ── Error ──────────────────────────────────────────────────────────────────────

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="border border-rose-500/20 bg-rose-500/5 rounded-xl px-4 py-3 text-rose-400 text-sm font-body">
      {message}
    </div>
  )
}

// ── API Status dot ─────────────────────────────────────────────────────────────

export function ApiDot({ online }: { online: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={cn(
          'w-1.5 h-1.5 rounded-full flex-shrink-0',
          online ? 'bg-emerald-400' : 'bg-rose-500'
        )}
        style={online ? { animation: 'pulse 2s infinite' } : {}}
      />
      <span className={cn('text-[10px] font-mono', online ? 'text-emerald-400/70' : 'text-rose-400/70')}>
        {online ? 'API online' : 'API offline'}
      </span>
    </span>
  )
}

// CSS injected for BorderBeam animation
if (typeof document !== 'undefined') {
  const style = document.createElement('style')
  style.textContent = `
    @keyframes beam-orbit {
      0% { left: -100%; }
      100% { left: 200%; }
    }
  `
  document.head.appendChild(style)
}
