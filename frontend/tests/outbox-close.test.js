/**
 * What the outbox does with each answer the server can give.
 *
 * Written because a successful close was being shown to the rep as a sync failure. The day was
 * pushed twice - once when it opened, once when it closed - and the server answers the second
 * push with `updated`, a status that did not exist until the day became one document. The outbox
 * retired `created` and `duplicate`, retried `held`, and treated **everything else** as rejected,
 * so `updated` fell through to that last branch: the row went `blocked`, the Sync Centre showed
 * the rep work that had not gone anywhere, and the day was correctly closed on the server the
 * whole time. Worse than a plain failure, because nothing a rep could do would clear it.
 *
 * None of the existing tests could have caught it. The server-side suite calls `sync.push`
 * directly and never sees the outbox; the outbox had no tests at all.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const push = vi.fn()

vi.mock('../src/api/client', () => ({
  api: { push: (...args) => push(...args) },
  ApiError: class ApiError extends Error {
    constructor(code) {
      super(code)
      this.code = code
    }
  },
}))

const { db } = await import('../src/db')
const { enqueue, drain, pendingCount, blockedCount } = await import('../src/sync/outbox')

/** `drain` returns early unless the browser says it is online. */
function online(is = true) {
  Object.defineProperty(navigator, 'onLine', { value: is, configurable: true })
}

/** The server's answer for whatever single record is in the batch. */
function answers(status, extra = {}) {
  push.mockImplementation(async (_device, batchUuid, records) => ({
    batch_uuid: batchUuid,
    results: records.map((r) => ({
      client_uuid: r.client_uuid,
      status,
      name: 'FM-DAY-00001',
      ...extra,
    })),
  }))
}

beforeEach(async () => {
  online(true)
  push.mockReset()
  await db.outbox.clear()
})

afterEach(() => {
  online(true)
})

describe('the answer to a close', () => {
  it('retires the queued record, the way a create does', async () => {
    // The whole point. `updated` means the close applied to the day it names.
    await enqueue('FieldMate Day', { closes: 'FM-DAY-00001', end_time: '2026-10-16 18:00:00' })
    answers('updated')

    await drain()

    expect(await db.outbox.count()).toBe(0)
    expect(await blockedCount()).toBe(0)
  })

  it('does not leave the rep looking at a failure that already worked', async () => {
    await enqueue('FieldMate Day', { closes: 'FM-DAY-00001' })
    answers('updated')

    await drain()

    expect(await blockedCount()).toBe(0)
    expect(await pendingCount()).toBe(0)
  })
})

describe('the other answers, so the fix did not widen anything', () => {
  it('retires a create', async () => {
    await enqueue('FieldMate Day', { start_time: '2026-10-16 09:00:00' })
    answers('created')
    await drain()
    expect(await db.outbox.count()).toBe(0)
  })

  it('retires a duplicate, because already there means already done', async () => {
    await enqueue('FieldMate Day', { start_time: '2026-10-16 09:00:00' })
    answers('duplicate')
    await drain()
    expect(await db.outbox.count()).toBe(0)
  })

  it('keeps a held record queued, to go again once its parent lands', async () => {
    await enqueue('FieldMate Visit', { outlet: 'OUT-1' })
    answers('held', { code: 'MISSING_PARENT' })
    await drain()

    const row = await db.outbox.toCollection().first()
    expect(row.state).toBe('queued')
    expect(row.attempts).toBe(1)
    expect(await blockedCount()).toBe(0)
  })

  it('blocks a rejected record and stops retrying it', async () => {
    await enqueue('FieldMate Visit', { outlet: 'OUT-1' })
    answers('rejected', { code: 'NOT_SYNCABLE', message: 'nope' })
    await drain()

    const row = await db.outbox.toCollection().first()
    expect(row.state).toBe('blocked')
    expect(row.lastError).toBe('nope')
    expect(await blockedCount()).toBe(1)
  })

  it('blocks a conflict and keeps the conflict to show somebody', async () => {
    await enqueue('FieldMate Visit', { outlet: 'OUT-1' })
    answers('conflict', { code: 'VALIDATION_FAILED', conflict: 'FM-CONF-0001' })
    await drain()

    const row = await db.outbox.toCollection().first()
    expect(row.state).toBe('blocked')
    expect(row.conflict).toBe('FM-CONF-0001')
  })
})
