/** Shrink a photo before it ever touches the network.
 *
 * The budget is 120 KB at 1280 px. A modern phone camera produces 4 MB files, and a day of
 * those would take longer to upload than the day took to work.
 */
export async function compress(file, { maxKb = 120, maxPx = 1280, quality = 0.7 } = {}) {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, maxPx / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height)

  let q = quality
  let dataUrl = canvas.toDataURL('image/jpeg', q)
  // Step the quality down rather than refusing: a slightly softer photo of a real shop beats
  // no photo at all.
  while (sizeKb(dataUrl) > maxKb && q > 0.3) {
    q -= 0.1
    dataUrl = canvas.toDataURL('image/jpeg', q)
  }
  return { dataUrl, kb: Math.round(sizeKb(dataUrl)), width: canvas.width, height: canvas.height }
}

function sizeKb(dataUrl) {
  return (dataUrl.length * 3) / 4 / 1024
}
