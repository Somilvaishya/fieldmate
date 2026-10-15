/** Shrink a photo before it ever touches the network.
 *
 * The budget is 120 KB at 1280 px. A modern phone camera produces 4 MB files, and a day of
 * those would take longer to upload than the day took to work.
 *
 * **WebP where the device can make one, JPEG where it cannot.** WebP holds the same picture in
 * roughly a third less space, which on a market uplink is the difference between a photo arriving
 * and a rep giving up on it. The server has accepted `image/webp` since the file service was
 * written, so nothing there has to change.
 */

/**
 * Which format this browser can actually encode.
 *
 * **The trap this exists for:** a canvas asked for a type it cannot encode does not fail. It
 * quietly returns a **PNG** instead. A PNG of a shop photo is several times larger than the JPEG
 * we have today, so a naive switch to WebP would have made every photo bigger on exactly the
 * older handsets that can least afford it — and nothing would have said so.
 *
 * So the answer is read back from a one-pixel canvas rather than assumed, and cached: it cannot
 * change while the app is open.
 */
let encodes = null

export function pickFormat(probe) {
  try {
    return probe().startsWith('data:image/webp') ? 'image/webp' : 'image/jpeg'
  } catch {
    // A browser that refuses the call at all, or a canvas with no 2d context behind it.
    return 'image/jpeg'
  }
}

function bestFormat() {
  if (encodes !== null) return encodes
  encodes = pickFormat(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    return canvas.toDataURL('image/webp')
  })
  return encodes
}

export async function compress(file, { maxKb = 120, maxPx = 1280, quality = 0.75 } = {}) {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, maxPx / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height)

  const type = bestFormat()

  let q = quality
  let dataUrl = canvas.toDataURL(type, q)
  // Step the quality down rather than refusing: a slightly softer photo of a real shop beats
  // no photo at all. WebP usually gets under the budget a step or two earlier, so the picture
  // that arrives is better than the JPEG one was at the same size.
  while (sizeKb(dataUrl) > maxKb && q > 0.3) {
    q -= 0.1
    dataUrl = canvas.toDataURL(type, q)
  }

  return {
    dataUrl,
    kb: Math.round(sizeKb(dataUrl)),
    width: canvas.width,
    height: canvas.height,
    // What it actually came out as, not what was asked for.
    type: dataUrl.slice(5, dataUrl.indexOf(';')),
  }
}

function sizeKb(dataUrl) {
  return (dataUrl.length * 3) / 4 / 1024
}
