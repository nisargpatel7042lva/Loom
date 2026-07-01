import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Trash2, AlertTriangle } from 'lucide-react'
import { api, type ForgetResult, type ForgetCandidate } from '../lib/api'
import {
  Card, Button, Slider, Toggle, Badge,
  BlurFade, SectionHeader, ErrorBox, Spinner, Empty, toast,
  WorkflowStepper, StepGuide,
} from './ui'

export default function ForgetPage() {
  const [dryRun, setDryRun] = useState(true)
  const [minFeedbacks, setMinFeedbacks] = useState(2)
  const [maxScore, setMaxScore] = useState(2)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ForgetResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await api.forget({ dry_run: dryRun, min_feedbacks: minFeedbacks, max_score: maxScore })
      setResult(res)
      const n = res.pruned.length
      if (dryRun) {
        toast(`${n} stale candidate(s) found — dry run only`, n > 0 ? 'info' : 'success')
      } else {
        toast(`${n} event(s) pruned from Cognee memory`, n > 0 ? 'success' : 'info')
      }
    } catch (e: any) {
      setError(e.message)
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <BlurFade>
      <WorkflowStepper current="forget" />

      <SectionHeader
        title="Forget"
        api="cognee.forget()"
        desc="Detect chronic false-positive precedents and remove them from Cognee's knowledge graph. Events with consistently low recall scores are pruned via cognee.forget(data_id, dataset_id) — zero LLM calls."
        llmCalls={0}
      />

      <StepGuide
        what="Step 4 of 4. Loom scans the feedback log for markets that consistently got low recall scores (avg ≤ threshold over N feedbacks). Run in dry-run mode first to preview what would be deleted — then flip the toggle and commit to actually prune those stale events from Cognee memory."
        prereqs={[
          'At least 2 Improve feedbacks recorded (step 3)',
          'At least one market with consistently low recall scores (avg ≤ 2)',
        ]}
        next="After pruning, head back to Remember to re-ingest fresh market data and start the cycle again."
        okCount={0}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Controls */}
        <Card className="p-6 lg:col-span-1 flex flex-col gap-5">
          <div className="space-y-2">
            <Toggle
              value={dryRun}
              onChange={setDryRun}
              label={dryRun ? 'Dry run (no deletion)' : 'Commit mode (will delete)'}
            />
            {!dryRun && (
              <div className="flex items-center gap-1.5 ml-1">
                <AlertTriangle size={11} className="text-rose-400/70 flex-shrink-0" />
                <p className="text-rose-400/60 text-[11px] font-mono">
                  Will call cognee.forget() — permanent deletion
                </p>
              </div>
            )}
          </div>

          <Slider
            label="Min feedbacks to qualify"
            value={minFeedbacks}
            onChange={setMinFeedbacks}
            min={1}
            max={10}
          />

          <Slider
            label="Max avg score (stale threshold)"
            value={maxScore}
            onChange={setMaxScore}
            min={1}
            max={4}
          />

          <div className="bg-white/[0.03] rounded-xl p-4 border border-white/[0.04] space-y-2">
            <p className="text-white/25 text-[10px] font-mono tracking-wide">Stale condition</p>
            <p className="text-white/50 text-xs font-body leading-relaxed">
              avg_score ≤ {maxScore} across ≥ {minFeedbacks} feedback entries
            </p>
            <p className="text-white/25 text-[10px] font-body mt-1">
              These events kept misleading recall and should be removed from memory.
            </p>
          </div>

          <div className="pt-2 border-t border-white/[0.06]">
            <div className="flex items-center justify-between text-xs font-mono text-white/30 mb-4">
              <span>Mode</span>
              <span className={dryRun ? 'text-amber-400' : 'text-rose-400'}>
                {dryRun ? 'Dry Run' : 'Commit'}
              </span>
            </div>
            <Button
              onClick={run}
              loading={loading}
              variant={!dryRun ? 'danger' : 'primary'}
              className="w-full"
            >
              {loading ? (
                'Scanning…'
              ) : dryRun ? (
                <span className="flex items-center gap-2">
                  <Search size={12} />
                  Scan for Stale Events
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <Trash2 size={12} />
                  Prune Stale Events
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
                <p className="text-white/50 text-sm font-body">Scanning feedback log…</p>
                <p className="text-white/20 text-xs font-mono">
                  find_stale_candidates() → cognee.datasets.list_data()
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
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    {[
                      {
                        label: 'Candidates',
                        value: result.candidates.length,
                        color: result.candidates.length > 0 ? 'text-amber-400' : 'text-emerald-400',
                      },
                      {
                        label: dryRun ? 'Would prune' : 'Pruned',
                        value: result.pruned.length,
                        color: result.pruned.length > 0 ? 'text-rose-400' : 'text-white/40',
                      },
                      {
                        label: 'Not found',
                        value: result.not_found.length,
                        color: 'text-white/40',
                      },
                      {
                        label: 'Mode',
                        value: result.dry_run ? 'Dry run' : 'Committed',
                        color: result.dry_run ? 'text-amber-400' : 'text-rose-400',
                      },
                    ].map((s) => (
                      <div key={s.label}>
                        <div className={`text-2xl font-mono font-light ${s.color}`}>{s.value}</div>
                        <div className="text-white/25 text-[10px] font-body mt-0.5">{s.label}</div>
                      </div>
                    ))}
                  </div>
                </Card>

                {result.candidates.length === 0 ? (
                  <Card className="p-8">
                    <Empty message="No stale candidates found. Either no feedback has been recorded yet, or all events have acceptable recall scores." />
                  </Card>
                ) : (
                  <div className="flex flex-col gap-3">
                    <p className="text-white/30 text-xs font-mono tracking-wide">
                      Stale candidates ({result.candidates.length})
                    </p>
                    {result.candidates.map((c, i) => (
                      <CandidateCard
                        key={c.market_id}
                        candidate={c}
                        index={i}
                        wasPruned={result.pruned.some((p) => p.market_id === c.market_id)}
                        dryRun={result.dry_run}
                      />
                    ))}
                  </div>
                )}

                <div className="border border-white/[0.06] rounded-xl px-4 py-3 space-y-1">
                  <p className="text-white/25 text-[10px] font-mono tracking-wide">Deletion scope</p>
                  <p className="text-white/35 text-xs font-body leading-relaxed">
                    cognee.forget() removes the Data record and all unique graph nodes/edges.
                    Shared entity nodes referenced by multiple events are detagged but not
                    removed — the graph stays coherent.
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {!loading && !result && !error && (
            <Card className="p-8">
              <Empty message='Configure thresholds and press "Scan for Stale Events". Use dry run to preview before committing any deletions.' />
            </Card>
          )}
        </div>
      </div>
    </BlurFade>
  )
}

function CandidateCard({
  candidate,
  index,
  wasPruned,
  dryRun,
}: {
  candidate: ForgetCandidate
  index: number
  wasPruned: boolean
  dryRun: boolean
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.07 }}
      className="liquid-glass border border-white/[0.06] rounded-xl p-4 space-y-3"
    >
      <div className="flex items-center justify-between gap-4">
        <span className="text-white font-mono text-sm">{candidate.market_id}</span>
        <div className="flex items-center gap-2">
          <Badge color="rose">avg {candidate.avg_score}/5</Badge>
          <Badge color="white">{candidate.feedback_count} feedbacks</Badge>
          {wasPruned && !dryRun && <Badge color="rose">pruned</Badge>}
          {wasPruned && dryRun && <Badge color="amber">would prune</Badge>}
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap">
        {candidate.scores.map((s, i) => (
          <div
            key={i}
            className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-mono ${
              s >= 4
                ? 'bg-emerald-400/20 text-emerald-400'
                : s >= 3
                ? 'bg-amber-400/20 text-amber-400'
                : 'bg-rose-400/20 text-rose-400'
            }`}
          >
            {s}
          </div>
        ))}
        <span className="text-white/20 text-[10px] font-mono ml-1">avg {candidate.avg_score}</span>
      </div>

      <p className="text-white/35 text-[11px] font-body leading-relaxed">{candidate.reason}</p>
    </motion.div>
  )
}
