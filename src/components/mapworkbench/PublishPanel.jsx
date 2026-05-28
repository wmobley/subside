export function PublishPanel({ suggestions, viewState, setViewState, publishForm, updateForm, jwtToken, handleApply }) {
  return (
    <section className="control-panel">
      <h3>Publish Update</h3>
      <label htmlFor="suggested-dataset">Suggested dataset</label>
      <select
        id="suggested-dataset"
        value={viewState.datasetSuggestion}
        onChange={(event) => {
          const value = event.target.value
          setViewState((current) => ({ ...current, datasetSuggestion: value }))
          if (value && value !== '__new__') updateForm('datasetName', value)
        }}
      >
        {suggestions.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>

      <label htmlFor="dataset-name">Dataset name</label>
      <input id="dataset-name" value={publishForm.datasetName} onChange={(event) => updateForm('datasetName', event.target.value)} />
      <label htmlFor="dataset-title">Dataset title</label>
      <input id="dataset-title" value={publishForm.datasetTitle} onChange={(event) => updateForm('datasetTitle', event.target.value)} />
      <label htmlFor="output-name">Output filename</label>
      <input id="output-name" value={publishForm.outputName} onChange={(event) => updateForm('outputName', event.target.value)} />
      <label htmlFor="source-url">Source URL</label>
      <input id="source-url" value={publishForm.sourceUrl} onChange={(event) => updateForm('sourceUrl', event.target.value)} />
      <label htmlFor="change-summary">Change summary</label>
      <textarea id="change-summary" value={publishForm.changeSummary} onChange={(event) => updateForm('changeSummary', event.target.value)} rows={4} />

      <button className="portal-btn publish-btn" type="button" disabled={!jwtToken} onClick={handleApply}>Apply and publish</button>
    </section>
  )
}
