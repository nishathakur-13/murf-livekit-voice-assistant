'use client';

import { useEffect, useState, useCallback } from 'react';

interface Escalation {
  reference_id: string;
  user_id: string;
  caller_name: string;
  situation_type: string;
  summary: string;
  urgency: 'low' | 'medium' | 'high' | 'emergency';
  language: string;
  follow_up_method: string;
  what_agent_tried: string;
  status: 'open' | 'in_progress' | 'resolved';
  created_at: string;
  updated_at: string;
}

const URGENCY_STYLES: Record<string, string> = {
  low: 'bg-green-100 text-green-800 border border-green-300',
  medium: 'bg-yellow-100 text-yellow-800 border border-yellow-300',
  high: 'bg-orange-100 text-orange-800 border border-orange-300',
  emergency: 'bg-red-100 text-red-800 border border-red-300 animate-pulse',
};

const STATUS_STYLES: Record<string, string> = {
  open: 'bg-blue-100 text-blue-800 border border-blue-300',
  in_progress: 'bg-purple-100 text-purple-800 border border-purple-300',
  resolved: 'bg-gray-100 text-gray-600 border border-gray-300',
};

const URGENCY_EMOJI: Record<string, string> = {
  low: '🟢',
  medium: '🟡',
  high: '🔴',
  emergency: '🚨',
};

const SITUATION_LABELS: Record<string, string> = {
  crop_emergency: '🌾 Crop Disease / Pest Emergency',
  farmer_crisis: '🆘 Farmer Distress / Crisis',
};

function formatTime(iso: string): string {
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

export default function EscalationsDashboard() {
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'open' | 'in_progress' | 'resolved'>('all');
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchEscalations = useCallback(async () => {
    try {
      const res = await fetch('/api/escalations', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        setEscalations(data.escalations || []);
        setLastRefresh(new Date());
      }
    } catch (err) {
      console.error('Failed to fetch escalations:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEscalations();
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchEscalations, 30000);
    return () => clearInterval(interval);
  }, [fetchEscalations]);

  const updateStatus = async (referenceId: string, status: string) => {
    setUpdating(referenceId);
    try {
      const res = await fetch('/api/escalations', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reference_id: referenceId, status }),
      });
      if (res.ok) {
        await fetchEscalations();
      }
    } catch (err) {
      console.error('Failed to update status:', err);
    } finally {
      setUpdating(null);
    }
  };

  const filtered = escalations.filter(
    (e) => filter === 'all' || e.status === filter
  );

  const counts = {
    all: escalations.length,
    open: escalations.filter((e) => e.status === 'open').length,
    in_progress: escalations.filter((e) => e.status === 'in_progress').length,
    resolved: escalations.filter((e) => e.status === 'resolved').length,
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-4 sm:p-6">
      {/* Header */}
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-6 gap-3">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              🌾 KrishiMitra Escalations
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Human escalation requests from farmers
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {lastRefresh ? `Last updated: ${lastRefresh.toLocaleTimeString('en-IN')}` : ''}
            </span>
            <button
              onClick={fetchEscalations}
              className="px-3 py-1.5 text-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition text-gray-700 dark:text-gray-200"
            >
              🔄 Refresh
            </button>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          {(['all', 'open', 'in_progress', 'resolved'] as const).map((s) => (
            <button
              key={s}
              onClick={() => setFilter(s)}
              className={`p-3 rounded-xl border text-center transition ${
                filter === s
                  ? 'bg-indigo-50 dark:bg-indigo-900/30 border-indigo-300 dark:border-indigo-600'
                  : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 hover:border-indigo-200 dark:hover:border-indigo-700'
              }`}
            >
              <div className="text-2xl font-bold text-gray-900 dark:text-white">
                {counts[s]}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400 capitalize mt-0.5">
                {s === 'in_progress' ? 'In Progress' : s.charAt(0).toUpperCase() + s.slice(1)}
              </div>
            </button>
          ))}
        </div>

        {/* Escalation cards */}
        {loading ? (
          <div className="text-center py-16 text-gray-400 dark:text-gray-500">
            Loading escalations...
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-5xl mb-3">🌾</div>
            <p className="text-gray-500 dark:text-gray-400">
              {filter === 'all'
                ? 'No escalations yet. Conversations will appear here when farmers need help.'
                : `No ${filter} escalations.`}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {filtered.map((esc) => (
              <div
                key={esc.reference_id}
                className={`bg-white dark:bg-gray-800 rounded-2xl border shadow-sm overflow-hidden ${
                  esc.urgency === 'emergency'
                    ? 'border-red-300 dark:border-red-700'
                    : 'border-gray-200 dark:border-gray-700'
                }`}
              >
                {/* Card header */}
                <div className="flex flex-wrap items-center justify-between gap-3 p-4 border-b border-gray-100 dark:border-gray-700">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm font-semibold text-indigo-600 dark:text-indigo-400">
                      {esc.reference_id}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${URGENCY_STYLES[esc.urgency] || ''}`}
                    >
                      {URGENCY_EMOJI[esc.urgency]} {esc.urgency.toUpperCase()}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[esc.status] || ''}`}
                    >
                      {esc.status.replace('_', ' ').toUpperCase()}
                    </span>
                  </div>
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    {formatTime(esc.created_at)}
                  </span>
                </div>

                {/* Card body */}
                <div className="p-4 grid sm:grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
                      Situation
                    </p>
                    <p className="text-sm text-gray-800 dark:text-gray-200">
                      {SITUATION_LABELS[esc.situation_type] || esc.situation_type}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
                      Caller
                    </p>
                    <p className="text-sm text-gray-800 dark:text-gray-200">
                      👤 {esc.caller_name}{' '}
                      <span className="text-gray-400">({esc.language})</span>
                    </p>
                  </div>
                  <div className="sm:col-span-2">
                    <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
                      Summary
                    </p>
                    <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                      {esc.summary}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
                      What Agent Tried
                    </p>
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      {esc.what_agent_tried}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">
                      Follow-up Method
                    </p>
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      📞 {esc.follow_up_method}
                    </p>
                  </div>
                </div>

                {/* Status actions */}
                <div className="flex flex-wrap items-center gap-2 px-4 py-3 bg-gray-50 dark:bg-gray-900/40 border-t border-gray-100 dark:border-gray-700">
                  <span className="text-xs text-gray-400 dark:text-gray-500 mr-1">
                    Update status:
                  </span>
                  {(['open', 'in_progress', 'resolved'] as const).map((s) => (
                    <button
                      key={s}
                      disabled={esc.status === s || updating === esc.reference_id}
                      onClick={() => updateStatus(esc.reference_id, s)}
                      className={`px-2.5 py-1 text-xs rounded-lg transition font-medium ${
                        esc.status === s
                          ? 'bg-gray-200 dark:bg-gray-700 text-gray-400 dark:text-gray-500 cursor-default'
                          : 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 hover:border-indigo-400 dark:hover:border-indigo-500 text-gray-700 dark:text-gray-200 cursor-pointer'
                      }`}
                    >
                      {s === 'in_progress' ? 'In Progress' : s.charAt(0).toUpperCase() + s.slice(1)}
                    </button>
                  ))}
                  {updating === esc.reference_id && (
                    <span className="text-xs text-gray-400 dark:text-gray-500 ml-2">
                      Updating...
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
