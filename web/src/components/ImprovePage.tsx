import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Sparkles, CheckCircle, XCircle, Clock } from 'lucide-react'
import { api, type MarketEvent, type ImproveResult } from '../lib/api'
import {
  Card, Button, Select, Badge,
  BlurFade, SectionHeader, ErrorBox, Spinner, Empty, toast,
} from './ui'

const OUTCOME_OPTIONS = [
  { value: 'YES', label: 'YES — resolved true' },
  { value: 'NO', label: 'NO — resolved false' },
  { value: 'pending', label: 'Pending — still open' },
]

const SCORE_LABELS: Record<number, string> = {
  1: 'Wrong direction',
  2: 'Mostly wrong',
  3: 'Neutral / ambiguous',
  4: 'Mostly correct',
  5: 'Perfect recall',
}

const OUTCOME_ICONS = {
  YES: <CheckCircle size={12} className="text-emerald-400" />,
  NO: <XCircle size={12} className="text-rose-400" />,
  pending: <Clock size={12} className="text-amber-400" />,
}

export default function ImprovePage() {
  const [events, setEvents] = useState<MarketEvent[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [outcome, setOutcome] = useState('YES')
  const [score, setScore] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ImproveResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.events().then((r) => {
      setEvents(r.events)
      if (r.events.length > 0) setSelectedId(r.events[0].market_id)
    })
  }, [])

  const selectedEvent = events.find((e) => e.market_id === selectedId)

  const run = async () => {
    if (!selectedId) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.improve({
        market_id: selectedId,
        actual_outcome: outcome,
        feedback_score: score ?? undefined,
      })
      setResult(res)
      const stored = res.feedback_results.filter((r) => r.add_feedback_returned).length
      toast(
        stored > 0
          ? `Feedback stored for ${stored} recall interaction(s)`
          : 'No prior recall interactions found for this market',
        stored > 0 ? 'success' : 'info'
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
        title="Improve"
        api="add_feedback()"
        desc="Record actual market outcomes and score recall quality 1–5. Feedback is stored in Cognee's session cache via session_manager.add_feedback() — zero LLM calls."
        llmCalls={0}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Controls */}
        <Card className="p-6 lg:col-span-1 flex flex-col gap-5">
          <Select
            label="Market to score"
            value={selectedId}
            onChange={setSelectedId}
            options={events.map((e) => ({
              value: e.market_id,
              label: `${e.market_id} — ${e.market_question.slice(0, 48)}…`,
            }))}
          />

          {selectedEvent && (
            <div className="bg-white/[0.03] rounded-xl p-4 border border-white/[0.04]">
              <p className="text-white/50 text-xs leading-relaxed font-body">
                {selectedEvent.market_question}
              </p>
              {selectedEvent.outcome && selectedEvent.outcome !== 'pending' && (
                <div className="mt-2 flex items-center gap-1.5">
                  <span className="text-white/25 text-[10px] font-mono">Known outcome:</span>
                  <span
                    className={`text-[10px] font-mono ${
                      selectedEvent.outcome === 'YES' ? 'text-emerald-400' : 'text-rose-400'
                    }`}
                  >
                    {selectedEvent.outcome}
                  </span>
                </div>
              )}
            </div>
          )}

          <Select
            label="Actual outcome"
            value={outcome}
            onChange={setOutcome}
            options={OUTCOME_OPTIONS}
          />

          {/* Manual score */}
          <div className="flex flex-col gap-2">
            <label className="text-white/40 text-xs font-mono tracking-wide">
              Override score (optional — auto-scored if blank)
            </label>
            <div className="flex gap-2">
              {([null, 1, 2, 3, 4, 5] as const).map((s) => (
                <button
                  key={String(s)}
                  onClick={() => setScore(s)}
                  className={`flex-1 py-2 rounded-lg text-xs font-mono transition-all ${
                    score === s
                      ? 'bg-amber-400 text-black'
                      : 'bg-white/[0.04] text-white/30 hover:text-white/60 border border-white/10'
                  }`}
                >
                  {s === null ? 'Auto' : s}
                </button>
              ))}
            </div>
            {score !== null && (
              <p className="text-white/30 text-[11px] font-body">{SCORE_LABELS[score]}</p>
            )}
          </div>

          <div className="pt-2 border-t border-white/[0.06]">
            <div className="flex items-center justify-between text-xs font-mono text-white/30 mb-4">
              <span>Cognee API</span>
              <span className="text-amber-400/70">add_feedback()</span>
            </div>
            <Button onClick={run} loading={loading} className="w-full">
              {loading ? (
                'Recording…'
              ) : (
                <span className="flex items-center gap-2">
                  <Sparkles size={12} />
                  Record Outcome
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
                <p className="text-white/50 text-sm font-body">Recording feedback…</p>
                <p className="text-white/20 text-xs font-mono">
                  get_session() → score_answer() → add_feedback()
                </p>
              </div>
            </Card>
          )}

          {error && <ErrorBox message={error} />}

          <AnimatePresence>
            {result && !loading && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex flex-col gap-4"
              >
                <Card className="p-5">
                  <div className="grid grid-cols-3 gap-4">
                    {[
                      { label: 'Market', value: result.market_id, color: 'text-white' },
                      {
                        label: 'Outcome recorded',
                        value: result.actual_outcome,
                        color:
                          result.actual_outcome === 'YES'
                            ? 'text-emerald-400'
                            : result.actual_outcome === 'NO'
                            ? 'text-rose-400'
                            : 'text-amber-400',
                      },
                      {
                        label: 'QA entries found',
                        value: String(result.qa_ids_found),
                        color: result.qa_ids_found > 0 ? 'text-emerald-400' : 'text-white/40',
                      },
                    ].map((s) => (
                      <div key={s.label}>
                        <div className={`text-lg font-mono ${s.color}`}>{s.value}</div>
                        <div className="text-white/25 text-[10px] font-body mt-0.5">{s.label}</div>
                      </div>
                    ))}
                  </div>
                </Card>

                {result.note && (
                  <div className="border border-amber-500/20 bg-amber-500/5 rounded-xl px-4 py-3 text-amber-400/70 text-xs font-body">
                    {result.note}
                  </div>
                )}

                {result.feedback_results.length > 0 ? (
                  <div className="flex flex-col gap-3">
                    <p className="text-white/30 text-xs font-mono tracking-wide">
                      Feedback results ({result.feedback_results.length})
                    </p>
                    {result.feedback_results.map((fb, i) => (
                      <motion.div
                        key={fb.qa_id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.06 }}
                        className="liquid-glass border border-white/[0.06] rounded-xl p-4 space-y-3"
                      >
                        <div className="flex items-center justify-between gap-4">
                          <span className="text-white/30 text-[10px] font-mono truncate">
                            qa_id: {fb.qa_id.slice(0, 16)}…
                          </span>
                          <Badge color={fb.add_feedback_returned ? 'green' : 'rose'}>
                            add_feedback → {fb.add_feedback_returned ? 'True' : 'False'}
                          </Badge>
                        </div>

                        <div className="flex items-center gap-3">
                          <span className="text-white/30 text-[10px] font-mono w-12">Score</span>
                          <div className="flex gap-1 flex-1">
                            {[1, 2, 3, 4, 5].map((n) => (
                              <div
                                key={n}
                                className={`h-1.5 flex-1 rounded-full transition-all ${
                                  n <= fb.score
                                    ? fb.score >= 4
                                      ? 'bg-emerald-400'
                                      : fb.score >= 2
                                      ? 'bg-amber-400'
                                      : 'bg-rose-400'
                                    : 'bg-white/10'
                                }`}
                              />
                            ))}
                          </div>
                          <span className="text-white/50 text-xs font-mono w-4">{fb.score}/5</span>
                        </div>

                        <p className="text-white/40 text-[11px] font-body leading-relaxed">
                          {fb.reasoning}
                        </p>
                      </motion.div>
                    ))}
                  </div>
                ) : (
                  <Card className="p-6">
                    <Empty message="No prior recall interactions found. Run Recall first so there is a QA entry to score." />
                  </Card>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          {!loading && !result && !error && (
            <Card className="p-8">
              <Empty message="Select a market, set its actual outcome, and press Record Outcome to store feedback via Cognee's session manager." />
            </Card>
          )}
        </div>
      </div>
    </BlurFade>
  )
}
