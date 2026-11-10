import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { getDisclaimer } from '../lib/content'
import { hashForPage } from '../lib/routes'

// Bump the version suffix when the terms change materially, so returning
// visitors are asked to accept again.
const STORAGE_KEY = 'subside.terms-accepted.v1'

// localStorage can throw (private windows, blocked site data); fall back to
// "not accepted" on read and a session-only acceptance on write.
function hasAccepted() {
  try { return window.localStorage.getItem(STORAGE_KEY) === '1' } catch { return false }
}
function rememberAccepted() {
  try { window.localStorage.setItem(STORAGE_KEY, '1') } catch { /* session-only */ }
}

// "Opened the terms" is shared across tabs too: the terms open in a new tab, and
// a visitor who browses on from there shouldn't be asked to click the link again.
const OPENED_KEY = 'subside.terms-opened.v1'
function hasOpenedTerms() {
  try { return window.localStorage.getItem(OPENED_KEY) === '1' } catch { return false }
}
function rememberOpenedTerms() {
  try { window.localStorage.setItem(OPENED_KEY, '1') } catch { /* this tab only */ }
}

// First-visit acceptance gate. Text lives in content/disclaimers/welcome.md.
// `suspended` hides it on the Terms page so visitors can read the full terms.
export function AcceptTermsModal({ suspended = false }) {
  const [accepted, setAccepted] = useState(hasAccepted)
  // The visitor must open the full terms before the accept button enables.
  const [openedTerms, setOpenedTerms] = useState(hasOpenedTerms)
  const linkRef = useRef(null)
  const open = !accepted && !suspended

  // Pick up acceptance / "opened" done in another tab.
  useEffect(() => {
    const onStorage = () => {
      setAccepted(hasAccepted())
      setOpenedTerms(hasOpenedTerms())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  useEffect(() => {
    if (open) linkRef.current?.focus()
  }, [open])

  if (!open) return null
  const welcome = getDisclaimer('welcome')
  if (!welcome.body) return null

  const markOpened = () => {
    rememberOpenedTerms()
    setOpenedTerms(true)
  }
  const accept = () => {
    if (!openedTerms) return
    rememberAccepted()
    setAccepted(true)
  }

  return (
    <div className="terms-modal-backdrop">
      <div
        className="terms-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="terms-modal-title"
      >
        <h2 id="terms-modal-title">{welcome.title || 'Terms of use'}</h2>
        <div className="terms-modal-body"><ReactMarkdown>{welcome.body}</ReactMarkdown></div>
        <p>
          <a
            href={hashForPage('terms')}
            target="_blank"
            rel="noreferrer"
            ref={linkRef}
            onClick={markOpened}
            onAuxClick={markOpened}
          >
            {welcome.link || 'Read the terms of use'}
          </a>
        </p>
        <div className="terms-modal-actions">
          <button
            type="button"
            className="terms-modal-accept"
            disabled={!openedTerms}
            aria-describedby={openedTerms ? undefined : 'terms-modal-hint'}
            onClick={accept}
          >
            {welcome.accept || 'I agree'}
          </button>
          {openedTerms ? null : (
            <span id="terms-modal-hint" className="terms-modal-hint">
              {welcome.hint || 'Open the terms of use to enable this button.'}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
