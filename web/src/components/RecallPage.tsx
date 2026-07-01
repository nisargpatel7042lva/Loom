import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Globe, List, PenLine } from 'lucide-react'
import { api, type MarketEvent, type AnalyzeResult } from '../lib/api'
import {
  Card, Button, Select, Input, Badge,
  BlurFade, SectionHeader, ErrorBox, ChunkCard, BriefCard, Spinner, Empty, toast,
} from './ui'

const CATEGORY_OPTIONS = [
  { value: 'macro', label: 'Macro / Economics' },
  { value: 'crypto', label: 'Crypto' },
  { value: 'elections', label: 'Elections / Politics' },
  { value: 'sports', label: 'Sports' },
]

type Mode = 'select' | 'custom'

export default function RecallPage({ memoryCount }: { memoryCount: number }) {
  const [mode, setMode] = useState<Mode>('select')
  const [events, setEvents] = useState<MarketEvent[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [customQ, setCustomQ] = useState('')
  const [customCat, setCustomCat] = useState('macro')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AnalyzeResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.events().then((r) => {
      setEvents(r.events)
      if (r.events.length > 0) setSelectedId(r.events[0].market_id)
    })
  }, [])

  const selectedEvent = events.find((e) => e.market_id === selectedId)

  const run = async () => {
    if (mode === 'select' && !selectedId) return
    if (mode === 'custom' && !customQ.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await api.analyze(
        mode === 'select'
          ? { market_id: selectedId }
          : { market_question: customQ, category: customCat }
      )
      setResult(res)
      toast(
        `${res.chunks.length} analogues found`,
        res.chunks.length > 0 ? 'success' : 'info'
      )
    } catch (e: any) {
      setError(e.message)
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <BlurFade>
      <SectionHeader
        title="Recall"
        api="cognee.search() + LLM"
        desc="Find analogous past markets via FastEmbed cosine similarity, then synthesize a trader brief with exactly one Gemini LLM call."
        llmCalls={1}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Controls */}
        <Card className="p-6 lg:col-span-1 flex flex-col gap-5">
          {/* Mode toggle */}
          <div className="flex flex-col gap-3">
            <label className="text-white/40 text-xs font-mono tracking-wide">Input mode</label>
            <div className="flex rounded-xl overflow-hidden border border-white/10">
              {([
                { id: 'select' as Mode, Icon: List, label: 'From fixtures' },
                { id: 'custom' as Mode, Icon: PenLine, label: 'Custom query' },
              ]).map(({ id, Icon, label }) => (
                <button
                  key={id}
                  onClick={() => setMode(id)}
                  className={`flex-1 py-2.5 text-xs font-mono transition-all flex items-center justify-center gap-1.5 ${
                    mode === id ? 'bg-white/10 text-white' : 'text-white/30 hover:text-white/60'
                  }`}
                >
                  <Icon size={11} />
                  {label}
                </button>
              ))}
            </div>
          </div>

          {mode === 'select' ? (
            <Select
              label="Select market"
              value={selectedId}
              onChange={setSelectedId}
              options={events.map((e) => ({
                value: e.market_id,
                label: `${e.market_id} — ${e.market_question.slice(0, 50)}…`,
              }))}
            />
          ) : (
            <>
              <Input
                label="Your market question"
                value={customQ}
                onChange={setCustomQ}
                placeholder="Will Bitcoin reach $150K in 2025?"
              />
              <Select
                label="Category"
                value={customCat}
                onChange={setCustomCat}
                options={CATEGORY_OPTIONS}
              />
            </>
          )}

          {/* Selected event preview */}
          {mode === 'select' && selectedEvent && (
            <div className="bg-white/[0.03] rounded-xl p-4 border border-white/[0.04] space-y-2">
              <p className="text-white/60 text-xs leading-relaxed font-body">
                {selectedEvent.market_question}
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <Badge color="white">{selectedEvent.category}</Badge>
                {selectedEvent.outcome && (
                  <Badge
                    color={
                      selectedEvent.outcome === 'YES'
                        ? 'green'
                        : selectedEvent.outcome === 'NO'
                        ? 'rose'
                        : 'white'
                    }
                  >
                    {selectedEvent.outcome}
                  </Badge>
                )}
                {selectedEvent.odds_after !== undefined && (
                  <Badge color="amber">
                    {(selectedEvent.odds_after * 100).toFixed(0)}% implied
                  </Badge>
                )}
              </div>
            </div>
          )}

          <div className="pt-2 border-t border-white/[0.06]">
            <div className="flex items-center justify-between text-xs font-mono text-white/30 mb-2">
              <span>Memory events</span>
              <span className={memoryCount > 0 ? 'text-amber-400' : 'text-rose-400/60'}>
                {memoryCount}
              </span>
            </div>
            {memoryCount === 0 && (
              <p className="text-amber-400/50 text-[11px] font-mono mb-3">
                No events in memory — go to Remember first
              </p>
            )}
            <Button onClick={run} loading={loading} className="w-full">
              {loading ? (
                'Analyzing…'
              ) : (
                <span className="flex items-center gap-2">
                  <Search size={12} />
                  Recall + Analyze
                </span>
              )}
            </Button>
          </div>
        </Card>

        {/* Results */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          {loading && (
            <Card className="p-8 flex flex-col items-center gap-4">
              <Spinner size="lg" />
              <div className="text-center space-y-1">
                <p className="text-white/50 text-sm font-body">Searching vector memory…</p>
                <p className="text-white/20 text-xs font-mono">
                  cognee.search(CHUNKS) + FastEmbed cosine similarity
                </p>
              </div>
            </Card>
          )}

          {error && <ErrorBox message={error} />}

          <AnimatePresence>
            {result && !loading && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col gap-4"
              >
                <BriefCard brief={result.brief} />

                <div className="flex items-center gap-4 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="text-white/30 text-xs font-mono">Analogues found</span>
                    <span className="text-amber-400 text-xs font-mono">{result.chunks.length}</span>
                  </div>
                  <div className="w-px h-3 bg-white/10" />
                  <div className="flex items-center gap-2">
                    <span className="text-white/30 text-xs font-mono">LLM calls</span>
                    <span className="text-amber-400 text-xs font-mono">1</span>
                  </div>
                  {result.qa_id && (
                    <>
                      <div className="w-px h-3 bg-white/10" />
                      <div className="flex items-center gap-2">
                        <span className="text-white/30 text-xs font-mono">qa_id</span>
                        <span className="text-white/40 text-xs font-mono truncate max-w-[120px]">
                          {result.qa_id.slice(0, 12)}…
                        </span>
                      </div>
                    </>
                  )}
                </div>

                {result.chunks.length > 0 ? (
                  <div className="flex flex-col gap-2">
                    <p className="text-white/30 text-xs font-mono tracking-wide">
                      Retrieved analogues ({result.chunks.length})
                    </p>
                    {result.chunks.map((chunk, i) => (
                      <ChunkCard key={i} text={chunk} index={i} />
                    ))}
                  </div>
                ) : (
                  <Empty message="No analogous events found. Ingest some events on the Remember page first." />
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {!loading && !result && !error && (
            <Card className="p-8">
              <Empty message="Select a market and press Recall + Analyze to find historical analogues and get a trader brief." />
            </Card>
          )}
        </div>
      </div>
    </BlurFade>
  )
}
