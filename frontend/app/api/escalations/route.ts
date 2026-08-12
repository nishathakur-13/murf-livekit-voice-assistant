import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

// Path to the escalations JSON file in the backend
const ESCALATIONS_PATH = path.join(
  process.cwd(),
  '..',
  'backend',
  'src',
  'escalations.json'
);

export const revalidate = 0;

function loadEscalations(): { escalations: unknown[] } {
  if (!fs.existsSync(ESCALATIONS_PATH)) {
    return { escalations: [] };
  }
  try {
    const raw = fs.readFileSync(ESCALATIONS_PATH, 'utf-8');
    const data = JSON.parse(raw);
    if (!data || !Array.isArray(data.escalations)) {
      return { escalations: [] };
    }
    return data;
  } catch {
    return { escalations: [] };
  }
}

// GET /api/escalations — return all escalations, newest first
export async function GET() {
  try {
    const data = loadEscalations();
    const sorted = [...data.escalations].sort((a: unknown, b: unknown) => {
      const aDate = (a as { created_at?: string }).created_at || '';
      const bDate = (b as { created_at?: string }).created_at || '';
      return bDate.localeCompare(aDate);
    });
    return NextResponse.json({ escalations: sorted });
  } catch (err) {
    console.error('GET /api/escalations error:', err);
    return NextResponse.json({ escalations: [] });
  }
}

// PATCH /api/escalations — update status of an escalation
export async function PATCH(req: Request) {
  try {
    const body = await req.json();
    const { reference_id, status } = body;

    if (!reference_id || !status) {
      return NextResponse.json({ error: 'reference_id and status required' }, { status: 400 });
    }

    const validStatuses = ['open', 'in_progress', 'resolved'];
    if (!validStatuses.includes(status)) {
      return NextResponse.json(
        { error: `status must be one of: ${validStatuses.join(', ')}` },
        { status: 400 }
      );
    }

    const data = loadEscalations();
    let found = false;
    for (const esc of data.escalations as Array<Record<string, unknown>>) {
      if (esc['reference_id'] === reference_id) {
        esc['status'] = status;
        esc['updated_at'] = new Date().toISOString().replace('.000Z', 'Z');
        found = true;
        break;
      }
    }

    if (!found) {
      return NextResponse.json({ error: 'Escalation not found' }, { status: 404 });
    }

    fs.writeFileSync(ESCALATIONS_PATH, JSON.stringify(data, null, 2), 'utf-8');
    return NextResponse.json({ success: true, reference_id, status });
  } catch (err) {
    console.error('PATCH /api/escalations error:', err);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
