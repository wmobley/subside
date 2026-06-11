// Client-side runtime estimate for an OPERA run, shown next to the product
// count so the user knows what they're in for before submitting.
//
// This is a MIRROR of analysis/h2i_lab/estimate.py — keep the constants in
// sync. It runs in the browser so the estimate updates instantly as the date
// window / pipeline changes, with no ASF round-trip. The API independently
// computes the *authoritative* job walltime at submit time from the same
// constants, so the number the job reserves never depends on this file.
//
// Constants measured on ls6 vm-small over 32 OPERA DISP-S1 products (2026-06).

const THROUGHPUT_MBPS = { 4: 67, 8: 97, 16: 88 } // aggregate download by worker count
const REALISTIC_FLOOR_MBPS = 55
const CONSERVATIVE_MBPS = 25 // walltime guard: ~1/4 of measured, absorbs throttling
const AVG_PRODUCT_MB = 450 // ~423 measured, rounded up
const FIXED_OVERHEAD_S = 40 // preflight + bbox parse + preview + staging
const WERC_FIXED_S = 300 // stack/reference/velocity/export, generous placeholder
const WERC_PER_PRODUCT_S = 8
const WALLTIME_SAFETY = 1.5
const WALLTIME_FLOOR_MIN = 30
const WALLTIME_CAP_MIN = 1440 // 24 h ceiling

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
  const downloadConservativeS = FIXED_OVERHEAD_S + (n * AVG_PRODUCT_MB) / CONSERVATIVE_MBPS
  const analysisS = pipeline === 'werc' ? WERC_FIXED_S + n * WERC_PER_PRODUCT_S : 0

  const estimatedS = downloadRealisticS + analysisS
  const guardedMin = ((downloadConservativeS + analysisS) * WALLTIME_SAFETY) / 60
  const walltimeMinutes = Math.round(
    Math.min(WALLTIME_CAP_MIN, Math.max(WALLTIME_FLOOR_MIN, Math.ceil(guardedMin))),
  )

  return {
    productCount: n,
    estimatedHuman: human(estimatedS),
    estimatedMinutes: Math.round((estimatedS / 60) * 10) / 10,
    walltimeMinutes,
    mayExceedWalltime: guardedMin > WALLTIME_CAP_MIN,
  }
}
