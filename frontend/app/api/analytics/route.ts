import { NextResponse } from 'next/server';

// Analytics server runs on port 8001 alongside the backend agent
const ANALYTICS_BASE = process.env.ANALYTICS_URL || 'http://localhost:8001';

// Disable caching so the dashboard always shows live data
export const revalidate = 0;

/**
 * GET /api/analytics?type=summary  — aggregate stats
 * GET /api/analytics?type=calls    — recent call history (last 50)
 * GET /api/analytics               — defaults to summary
 */
export async function GET(req: Request) {
  const url = new URL(req.url);
  const type = url.searchParams.get('type') || 'summary';

  const endpoint = type === 'calls' ? '/analytics/calls' : '/analytics/summary';

  try {
    const res = await fetch(`${ANALYTICS_BASE}${endpoint}`, {
      headers: { Accept: 'application/json' },
      // Next.js server-side fetch — don't cache
      cache: 'no-store',
    });

    if (!res.ok) {
      const text = await res.text();
      console.error(`Analytics server error (${res.status}):`, text);
      return NextResponse.json({ error: `Analytics server returned ${res.status}` }, { status: 502 });
    }

    const data = await res.json();
    return NextResponse.json(data, {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch (err) {
    // Analytics server not running — return safe empty state so the dashboard
    // still renders rather than crashing
    console.error('Could not reach analytics server:', err);

    if (type === 'calls') {
      return NextResponse.json(
        { calls: [], count: 0, _offline: true },
        { status: 200 }
      );
    }

    return NextResponse.json(
      {
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
      },
      { status: 200 }
    );
  }
}
