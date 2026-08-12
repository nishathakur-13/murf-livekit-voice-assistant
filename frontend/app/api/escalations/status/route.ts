import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

const ESCALATIONS_PATH = path.join(
  process.cwd(),
  '..',
  'backend',
  'src',
  'escalations.json'
);

export const revalidate = 0;

function loadEscalations(): { escalations: Array<Record<string, unknown>> } {
  if (!fs.existsSync(ESCALATIONS_PATH)) {
    return { escalations: [] };
  }
  try {
    const raw = fs.readFileSync(ESCALATIONS_PATH, 'utf-8');
    const data = JSON.parse(raw);
    if (!data || !Array.isArray(data.escalations)) return { escalations: [] };
    return data;
  } catch {
    return { escalations: [] };
  }
}

// GET /api/escalations/status?id=ESC-XXXXXX
export async function GET(req: Request) {
  const url = new URL(req.url);
  const id = url.searchParams.get('id');

  if (!id) {
    return NextResponse.json({ error: 'id query param required' }, { status: 400 });
  }

  const data = loadEscalations();
  const esc = data.escalations.find((e) => e['reference_id'] === id);

  if (!esc) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  return NextResponse.json({
    reference_id: esc['reference_id'],
    status: esc['status'],
    urgency: esc['urgency'],
    created_at: esc['created_at'],
    updated_at: esc['updated_at'],
  });
}
