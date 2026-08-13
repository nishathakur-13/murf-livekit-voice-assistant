'use client';

import { useCallback, useEffect, useState } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AnalyticsSummary {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  in_progress_calls: number;
  success_rate: number;
  escalated_calls: number;
  failure_breakdown: {
    user_hangup: number;
    incomplete_task: number;
    api_error: number;
    no_response: number;
    other: number;
  };
  _offline?: boolean;
}

interface CallRecord {
  session_id: string;
  channel: string;
  started_at: string;
  ended_at: string | null;
  duration_sec: number | null;
  outcome: 'success' | 'failed' | 'in_progress';
  failure_type: string | null;
  language: string | null;
  escalated: number;
  notes: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(sec: number | null): string {
  if (sec === null || sec === undefined) return '—';
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m ${s}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

function formatFailureType(ft: string | null): string {
  if (!ft) return '—';
  const labels: Record<string, string> = {
    user_hangup: 'Early Disconnect',
    incomplete_task: 'Incomplete Task',
    api_error: 'API Error',
    no_response: 'No Response',
  };
  return labels[ft] ?? ft.replace(/_/g, ' ');
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  sub,
  color,
  icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  color: string;
  icon: string;
}) {
  return (
    <div className={`rounded-2xl border p-6 shadow-sm ${color}`}>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-2xl">{icon}</span>
        <span className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</span>
      </div>
      <div className="text-4xl font-bold tracking-tight">{value}</div>
      {sub && <div className="mt-1 text-sm text-gray-500 dark:text-gray-400">{sub}</div>}
    </div>
  );
}

function ProgressBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
      <div
        className={`h-full rounded-full transition-all duration-700 ${color}`}
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </div>
  );
}

const OUTCOME_BADGE: Record<string, string> = {
  success: 'bg-green-100 text-green-800 border border-green-300',
  failed: 'bg-red-100 text-red-800 border border-red-300',
  in_progress: 'bg-blue-100 text-blue-800 border border-blue-300 animate-pulse',
};

const CHANNEL_BADGE: Record<string, string> = {
  web: 'bg-indigo-100 text-indigo-800 border border-indigo-300',
  sip: 'bg-purple-100 text-purple-800 border border-purple-300',
};

// ---------------------------------------------------------------------------
// Main dashboard page
// ---------------------------------------------------------------------------

export default function AnalyticsDashboard() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [calls, setCalls] = useState<CallRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [summaryRes, callsRes] = await Promise.all([
        fetch('/api/analytics?type=summary', { cache: 'no-store' }),
        fetch('/api/analytics?type=calls', { cache: 'no-store' }),
      ]);

      const summaryData: AnalyticsSummary = await summaryRes.json();
      const callsData: { calls: CallRecord[] } = await callsRes.json();

      setSummary(summaryData);
      setCalls(callsData.calls ?? []);
      setLastRefresh(new Date());
      setError(null);
    } catch (err) {
      console.error('Failed to fetch analytics:', err);
      setError('Could not load analytics data. Make sure the analytics server is running.');
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh every 10 seconds for live updates
  useEffect(() => {
    const timer = setInterval(fetchData, 10_000);
    return () => clearInterval(timer);
  }, [fetchData]);

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 dark:bg-gray-950">
        <div className="flex flex-col items-center gap-4">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-green-500 border-t-transparent" />
          <p className="text-gray-500">Loading analytics…</p>
        </div>
      </div>
    );
  }

  const s = summary ?? {
    total_calls: 0,
    successful_calls: 0,
    failed_calls: 0,
    in_progress_calls: 0,
    success_rate: 0,
    escalated_calls: 0,
    failure_breakdown: {
      user_hangup: 0,
      incomplete_task: 0,
      api_error: 0,
      no_response: 0,
      other: 0,
    },
    _offline: true,
  };

  const failureModes = [
    { key: 'user_hangup', label: 'Early Disconnect', icon: '📵' },
    { key: 'incomplete_task', label: 'Incomplete Task', icon: '⏸️' },
    { key: 'api_error', label: 'API Error', icon: '⚠️' },
    { key: 'no_response', label: 'No Response', icon: '🔇' },
    { key: 'other', label: 'Other', icon: '❓' },
  ];

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* ------------------------------------------------------------------ */}
      {/* Header */}
      {/* ------------------------------------------------------------------ */}
      <div className="border-b bg-white shadow-sm dark:bg-gray-900">
        <div className="mx-auto max-w-6xl px-6 py-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3">
                <span className="text-3xl">🌾</span>
                <div>
                  <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                    KrishiMitra AI — Call Analytics
                  </h1>
                  <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
                    Real-time dashboard · Farm &amp; Field track · Powered by{' '}
                    <span className="font-semibold text-indigo-600">Murf Falcon TTS</span>
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {s._offline && (
                <span className="rounded-full border border-yellow-300 bg-yellow-100 px-3 py-1 text-xs font-medium text-yellow-800">
                  ⚠️ Analytics server offline
                </span>
              )}
              {lastRefresh && (
                <span className="text-xs text-gray-400">
                  Updated {lastRefresh.toLocaleTimeString()}
                </span>
              )}
              <button
                onClick={fetchData}
                className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
              >
                ↻ Refresh
              </button>
              <a
                href="/"
                className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
              >
                ← Back to Voice Agent
              </a>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl space-y-8 px-6 py-8">
        {/* ---------------------------------------------------------------- */}
        {/* Error banner */}
        {/* ---------------------------------------------------------------- */}
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
            <strong>⚠️ Error:</strong> {error}
            <p className="mt-1 text-sm opacity-80">
              Start the analytics server:{' '}
              <code className="rounded bg-red-100 px-1 py-0.5 font-mono text-xs dark:bg-red-900">
                cd backend && uv run python src/analytics_server.py
              </code>
            </p>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Success definition banner */}
        {/* ---------------------------------------------------------------- */}
        <div className="rounded-xl border border-green-200 bg-green-50 px-5 py-4 dark:border-green-800 dark:bg-green-950">
          <p className="text-sm font-medium text-green-800 dark:text-green-300">
            ✅ <strong>Success definition (Farm &amp; Field):</strong> A call is{' '}
            <strong>successful</strong> when the farmer receives the agent&apos;s response — even if they
            hang up normally after. A call <strong>fails</strong> only if the farmer disconnects{' '}
            <em>before</em> the agent responds at all, or there is a technical error.
          </p>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Primary stats — 3 required numbers */}
        {/* ---------------------------------------------------------------- */}
        <div>
          <h2 className="mb-4 text-lg font-semibold text-gray-700 dark:text-gray-300">
            Call Outcomes
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <StatCard
              label="Total Calls"
              value={s.total_calls}
              sub={s.in_progress_calls > 0 ? `${s.in_progress_calls} in progress` : undefined}
              color="bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-700"
              icon="📞"
            />
            <StatCard
              label="Successful Calls"
              value={s.successful_calls}
              sub={
                s.escalated_calls > 0 ? `${s.escalated_calls} escalated to expert` : undefined
              }
              color="bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800 text-green-900 dark:text-green-100"
              icon="✅"
            />
            <StatCard
              label="Failed Calls"
              value={s.failed_calls}
              sub="Farmer left before getting help"
              color="bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800 text-red-900 dark:text-red-100"
              icon="❌"
            />
          </div>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Success rate + progress bar */}
        {/* ---------------------------------------------------------------- */}
        <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              📊 Success Rate
            </span>
            <span className="text-2xl font-bold text-gray-900 dark:text-white">
              {s.success_rate}%
            </span>
          </div>
          <ProgressBar pct={s.success_rate} color="bg-green-500" />
          <div className="mt-2 flex justify-between text-xs text-gray-400">
            <span>0%</span>
            <span>
              {s.successful_calls + s.failed_calls} completed calls
            </span>
            <span>100%</span>
          </div>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Failure breakdown */}
        {/* ---------------------------------------------------------------- */}
        {s.failed_calls > 0 && (
          <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h2 className="mb-4 text-sm font-semibold text-gray-700 dark:text-gray-300">
              ❌ Failure Breakdown
            </h2>
            <div className="space-y-3">
              {failureModes.map(({ key, label, icon }) => {
                const count = (s.failure_breakdown as Record<string, number>)[key] ?? 0;
                const pct = s.failed_calls > 0 ? (count / s.failed_calls) * 100 : 0;
                return (
                  <div key={key}>
                    <div className="mb-1 flex items-center justify-between text-sm">
                      <span className="text-gray-600 dark:text-gray-400">
                        {icon} {label}
                      </span>
                      <span className="font-semibold text-gray-800 dark:text-gray-200">
                        {count}
                      </span>
                    </div>
                    <ProgressBar pct={pct} color="bg-red-400" />
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Recent call history table */}
        {/* ---------------------------------------------------------------- */}
        <div>
          <h2 className="mb-4 text-lg font-semibold text-gray-700 dark:text-gray-300">
            Recent Call History
          </h2>

          {calls.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center dark:border-gray-700 dark:bg-gray-900">
              <p className="text-4xl">📵</p>
              <p className="mt-3 text-gray-500">No calls recorded yet.</p>
              <p className="mt-1 text-sm text-gray-400">
                Make a call from the voice agent to see data here.
              </p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b bg-gray-50 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
                      <th className="px-5 py-3">Time</th>
                      <th className="px-5 py-3">Duration</th>
                      <th className="px-5 py-3">Channel</th>
                      <th className="px-5 py-3">Language</th>
                      <th className="px-5 py-3">Outcome</th>
                      <th className="px-5 py-3">Failure Type</th>
                      <th className="px-5 py-3">Escalated</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {calls.map((call) => (
                      <tr
                        key={call.session_id}
                        className="transition-colors hover:bg-gray-50 dark:hover:bg-gray-800"
                      >
                        <td className="px-5 py-3 text-gray-700 dark:text-gray-300">
                          {formatTime(call.started_at)}
                        </td>
                        <td className="px-5 py-3 text-gray-700 dark:text-gray-300">
                          {formatDuration(call.duration_sec)}
                        </td>
                        <td className="px-5 py-3">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${CHANNEL_BADGE[call.channel] ?? 'bg-gray-100 text-gray-600'}`}
                          >
                            {call.channel === 'sip' ? '📱 SIP' : '🌐 Web'}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-gray-600 dark:text-gray-400">
                          {call.language ?? '—'}
                        </td>
                        <td className="px-5 py-3">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${OUTCOME_BADGE[call.outcome] ?? 'bg-gray-100 text-gray-600'}`}
                          >
                            {call.outcome === 'in_progress'
                              ? '⏳ Live'
                              : call.outcome === 'success'
                                ? '✅ Success'
                                : '❌ Failed'}
                          </span>
                        </td>
                        <td className="px-5 py-3 text-gray-600 dark:text-gray-400">
                          {formatFailureType(call.failure_type)}
                        </td>
                        <td className="px-5 py-3 text-center">
                          {call.escalated ? (
                            <span title="Escalated to human expert">🆘</span>
                          ) : (
                            <span className="text-gray-300 dark:text-gray-600">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Footer */}
        {/* ---------------------------------------------------------------- */}
        <div className="border-t pt-6 text-center text-xs text-gray-400 dark:text-gray-600">
          <p>
            KrishiMitra AI · Day 8 Analytics Dashboard · Part of{' '}
            <strong>#10DaysOfVoiceAgents</strong> ·{' '}
            <a
              href="https://murf.ai/api"
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-500 hover:underline"
            >
              Powered by Murf Falcon
            </a>
          </p>
          <p className="mt-1">
            Auto-refreshes every 10 seconds · No sensitive caller data displayed
          </p>
        </div>
      </div>
    </div>
  );
}
