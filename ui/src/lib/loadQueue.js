// Bounded concurrency gate shared by every StacCogLayer instance. A COG
// streams fine on its own via HTTP range requests -- that's the whole point
// of the format. The problem is opening 20+ of them at the exact same
// instant: the browser caps concurrent connections per origin (~6 on
// HTTP/1.1, which is what ckan.tacc.utexas.edu serves), so a burst of
// simultaneous "open + read header" calls queues up and starves itself,
// leaving some tiles abandoned ("missing blocks") rather than actually
// failing. This staggers that expensive open phase into small waves instead
// of firing them all at once; each layer streams normally once it's its turn.
const MAX_CONCURRENT_LOADS = 4
let active = 0
const queue = []

function pump() {
  while (active < MAX_CONCURRENT_LOADS && queue.length > 0) {
    const item = queue.shift()
    if (item.isCancelled?.()) continue // skip without spending a slot
    active += 1
    item.fn().then(
      (value) => { active -= 1; item.resolve(value); pump() },
      (err) => { active -= 1; item.reject(err); pump() },
    )
  }
}

// `fn` does the expensive open/parse step; `isCancelled` (optional) lets a
// caller that unmounted while queued skip its turn instead of loading for no
// reason.
export function withLoadSlot(fn, isCancelled) {
  return new Promise((resolve, reject) => {
    queue.push({ fn, resolve, reject, isCancelled })
    pump()
  })
}
