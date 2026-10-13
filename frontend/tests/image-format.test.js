/**
 * Which format a photo is encoded as before it leaves the phone.
 *
 * WebP holds the same picture in roughly a third less space, which on a market uplink is the
 * difference between a photo arriving and a rep giving up on it. The server has accepted
 * `image/webp` since the file service was written.
 *
 * **The whole reason this file exists is one trap.** A canvas asked for a type it cannot encode
 * does not fail and does not say so — it quietly returns a **PNG**. A PNG of a shop photo is
 * several times larger than the JPEG we send today, so switching to WebP without reading the
 * answer back would have made every photo bigger on exactly the older handsets that can least
 * afford it, and nothing anywhere would have reported it.
 */
import { describe, it, expect } from 'vitest'
import { pickFormat } from '../src/lib/image'

describe('what the browser can actually encode', () => {
  it('uses WebP when the canvas really produced one', () => {
    expect(pickFormat(() => 'data:image/webp;base64,UklGRg==')).toBe('image/webp')
  })

  it('falls back to JPEG when the canvas quietly returned a PNG', () => {
    // The trap. Chrome, Firefox and recent Safari answer WebP; an older WebView answers this,
    // with no error and no warning, and a photo three times the size.
    expect(pickFormat(() => 'data:image/png;base64,iVBORw0KGgo=')).toBe('image/jpeg')
  })

  it('falls back when the browser refuses the call altogether', () => {
    expect(pickFormat(() => { throw new Error('no 2d context') })).toBe('image/jpeg')
  })

  it('falls back on an empty answer rather than throwing', () => {
    // A canvas with no dimensions can answer "data:,". Whatever it is, it is not WebP.
    expect(pickFormat(() => 'data:,')).toBe('image/jpeg')
  })

  it('is not fooled by the word webp appearing later in the payload', () => {
    // base64 is base64; it can contain anything. Only the prefix says what the thing is.
    expect(pickFormat(() => 'data:image/png;base64,d2VicA==')).toBe('image/jpeg')
  })
})
