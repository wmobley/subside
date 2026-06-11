// Client-side runtime estimate for an OPERA run, shown next to the product
// count so the user knows what they're in for before submitting.
//
// This is a MIRROR of analysis/h2i_lab/estimate.py — keep the constants in
// sync. It runs in the browser so the estimate updates instantly as the date
// window / pipeline changes, with no ASF round-trip. The API independently
// computes the *authoritative* job walltime at submit time from the same
// constants, so the number the job reserves never depends on this file.
//
// Constants from the ls6 download-scaling run (2026-06, 2..100 products, 8
// workers). Throughput is not flat: it peaks ~87 MB/s near N=25 then throttles
// to ~63 MB/s by N=100, so the realistic rate sits near the sustained end so
// large runs aren't underestimated.

const THROUGHPUT_MBPS = { 4: 48, 8: 68, 16: 64 } // sustained aggregate by worker count
const REALISTIC_FLOOR_MBPS = 45
const AVG_PRODUCT_MB = 420 // measured 418-422 MB per full product
const FIXED_OVERHEAD_S = 25 // connection ramp + bbox parse (ramp folded into the rate)
const WERC_FIXED_S = 300 // stack/reference/velocity/export, generous placeholder
const WERC_PER_PRODUCT_S = 8
// Flat 12 h job reservation — the job frees its node when done, so the cap is a
// safety ceiling, not a cost; 12 h clears even the slow/throttled worst case.
const WALLTIME_MIN = 720

function realisticMbps(numWorkers) {
  const keys = Object.keys(THROUGHPUT_MBPS).map(Number)
  const nearest = keys.reduce((a, b) =>
    Math.abs(b - numWorkers) < Math.abs(a - numWorkers) ? b : a,
  )
  return Math.max(REALISTIC_FLOOR_MBPS, THROUGHPUT_MBPS[nearest])
}

function human(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60))
  if (minutes < 60) return `~${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `~${h} h ${m} min` : `~${h} h`
}

export function estimateRuntime(productCount, { pipeline = 'h2i', numWorkers = 8 } = {}) {
  const n = Math.max(0, Math.floor(productCount || 0))
  const realistic = realisticMbps(numWorkers)
  const downloadRealisticS = FIXED_OVERHEAD_S + (n * AVG_PRODUCT_MB) / realistic
  const analysisS = pipeline === 'werc' ? WERC_FIXED_S + n * WERC_PER_PRODUCT_S : 0
  const estimatedS = downloadRealisticS + analysisS

  return {
    productCount: n,
    estimatedHuman: human(estimatedS),
    estimatedMinutes: Math.round((estimatedS / 60) * 10) / 10,
    walltimeMinutes: WALLTIME_MIN,
    mayExceedWalltime: estimatedS / 60 > WALLTIME_MIN,
  }
}
