import ReactMarkdown from 'react-markdown'
import { getDisclaimer } from '../lib/content'

// Short in-tool legal banner. Text is editable in content/disclaimers/<id>.md.
export function DisclaimerBanner({ id }) {
  const { title, body } = getDisclaimer(id)
  if (!body) return null
  return (
    <aside className="tool-disclaimer" role="note">
      <ReactMarkdown>{`**${title ? `${title}.` : 'Notice.'}** ${body}`}</ReactMarkdown>
    </aside>
  )
}
