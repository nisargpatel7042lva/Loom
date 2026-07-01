import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, Globe, Database, CheckCircle } from 'lucide-react'
import { api, type RememberResult } from '../lib/api'
import {
  Card, Button, Select, Slider,
  BlurFade, SectionHeader, ErrorBox, Spinner, Badge, toast,
  WorkflowStepper, StepGuide, NextStepBanner,
} from './ui'

const LIVE_CATEGORIES = [
  { value: '', label: 'All categories' },
  { value: 'economics', label: 'Economics' },
  { value: 'crypto', label: 'Crypto' },
  { value: 'politics', label: 'Politics' },
  { value: 'sports', label: 'Sports' },
]

export default function RememberPage({
  onMemoryUpdate,
  onNavigate,
}: {
  onMemoryUpdate: () => void
  onNavigate: (page: string) => void
}) {
  const [category, setCategory] = useState('')
  const [maxEvents, setMaxEvents] = useState(10)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<RememberResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)

  const run = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    setProgress(0)

    const ticker = setInterval(() => {
      setProgress((p) => Math.min(p + Math.random() * 12, 88))
    }, 400)

    try {
      const res = await api.remember({
        source: 'live',
        category: category || undefined,
        max_events: maxEvents,
      })
      clearInterval(ticker)
      setProgress(100)
      setResult(res)
      onMemoryUpdate()
      toast(`${res.events_ingested} live events stored in Cognee memory`, 'success')
    } catch (e: any) {
      clearInterval(ticker)
      setProgress(0)
      setError(e.message)
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <BlurFade>
      <WorkflowStepper current="remember" />

      <SectionHeader
        title="Remember"
        api="cognee.add()"
        desc="Fetches live Jupiter prediction markets and ingests them into Cognee vector memory using local FastEmbed vectorization. Zero LLM calls."
        llmCalls={0}
      />

      <StepGuide
        what="This is step 1 of 4. Choose a category and how many markets to pull, then press 'Remember into Cognee'. Loom fetches live prediction markets from Jupiter and stores them as vector embeddings — no LLM calls, just fast local indexing."
        prereqs={['Backend running at localhost:8000 (start with uvicorn api.main:app --reload --port 8000)']}
        next="Once you've ingested some events, go to Recall to search your memory and get an AI-synthesized brief for any market."
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Controls */}
        <Card className="p-6 lg:col-span-1 flex flex-col gap-5">
          {/* Source indicator — always live */}
          <div className="flex items-center gap-2.5 bg-white/[0.03] border border-white/[0.06] rounded-xl px-4 py-3">
            <Globe size={13} className="text-amber-400 flex-shrink-0" />
            <div>
              <div className="text-white/70 text-xs font-mono">Live Jupiter API</div>
              <div className="text-white/25 text-[10px] font-body mt-0.5">
                Real-time prediction market data
              </div>
            </div>
          </div>

          <Select
            label="Category filter"
            value={category}
            onChange={setCategory}
            options={LIVE_CATEGORIES}
          />

          <Slider
            label="Max events to ingest"
            value={maxEvents}
            onChange={setMaxEvents}
            min={1}
            max={50}
          />

          <div className="pt-2 border-t border-white/[0.06]">
            <div className="flex items-center justify-between text-xs font-mono text-white/30 mb-4">
              <span>LLM calls</span>
              <span className="text-emerald-400">0</span>
            </div>
            <Button onClick={run} loading={loading} className="w-full">
              {loading ? (
                'Remembering…'
              ) : (
                <span className="flex items-center gap-2">
                  <Play size={12} />
                  Remember into Cognee
                </span>
              )}
            </Button>
          </div>
        </Card>

        {/* Result */}
        <Card className="p-6 lg:col-span-2 flex flex-col gap-5">
          <div className="flex items-center justify-between">
            <span className="text-white/40 text-xs font-mono tracking-wide">Result</span>
            {result && <Badge color="green">COMPLETED</Badge>}
          </div>

          {loading && (
            <div className="flex flex-col gap-4 py-8">
              <div className="flex items-center justify-center">
                <Spinner size="lg" />
              </div>
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-mono text-white/30">
                  <span>cognee.add() + FastEmbed vectorization</span>
                  <span>{Math.round(progress)}%</span>
                </div>
                <div className="h-1 bg-white/5 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-amber-400 rounded-full"
                    animate={{ width: `${progress}%` }}
                    transition={{ ease: 'linear', duration: 0.4 }}
                  />
                </div>
              </div>
            </div>
          )}

          {error && <ErrorBox message={error} />}

          <AnimatePresence>
            {result && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex flex-col gap-4"
              >
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Events ingested', value: String(result.events_ingested), color: 'text-white' },
                    { label: 'Dataset', value: result.dataset_name.replace('loom_', ''), color: 'text-amber-400/80' },
                    { label: 'Status', value: result.status, color: result.status === 'COMPLETED' ? 'text-emerald-400' : 'text-amber-400' },
                    { label: 'Elapsed', value: `${result.elapsed_seconds}s`, color: 'text-white/60' },
                  ].map((s) => (
                    <div
                      key={s.label}
                      className="bg-white/[0.03] rounded-xl p-4 border border-white/[0.06]"
                    >
                      <div className={`text-xl font-mono font-light ${s.color} truncate`}>
                        {s.value}
                      </div>
                      <div className="text-white/25 text-[10px] mt-1 font-body">{s.label}</div>
                    </div>
                  ))}
                </div>

                <div className="bg-white/[0.03] rounded-xl p-4 border border-white/[0.04]">
                  <p className="text-white/20 text-[10px] font-mono mb-2">Under the hood</p>
                  <div className="space-y-1.5">
                    {[
                      `await cognee.add(data=[text], dataset_name="${result.dataset_name}")`,
                      `vs_upsert(market_id, text)   # FastEmbed BAAI/bge-small-en-v1.5`,
                      `# repeated × ${result.events_ingested} events — 0 LLM calls`,
                    ].map((line, i) => (
                      <p key={i} className="text-amber-400/70 text-[11px] font-mono leading-relaxed">
                        {line}
                      </p>
                    ))}
                  </div>
                </div>

                <NextStepBanner
                  message={`${result.events_ingested} events stored. Ready to recall and analyze.`}
                  label="Go to Recall"
                  onGo={() => onNavigate('recall')}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {!loading && !result && !error && (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <div className="w-12 h-12 rounded-full border border-white/[0.06] flex items-center justify-center">
                <Database size={20} className="text-white/15" />
              </div>
              <p className="text-white/20 text-sm font-body text-center max-w-xs">
                Select a category and press "Remember" to fetch live Jupiter markets into Cognee
              </p>
            </div>
          )}
        </Card>
      </div>
    </BlurFade>
  )
}
