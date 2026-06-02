export function DatasetPanel({ datasets, dataset, setDataset, summary, selectedCount }) {
  return (
    <section className="control-panel">
      <h3>Dataset</h3>
      <label htmlFor="dataset-select">Dataset</label>
      <select
        id="dataset-select"
        value={dataset}
        onChange={(event) => setDataset(event.target.value)}
        disabled={!datasets.length}
      >
        {!datasets.length ? <option value="">Loading datasets</option> : null}
        {datasets.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      <div className="inline-metrics">
        <span>{summary.activeCellCount} active cells</span>
        <span>{selectedCount} selected</span>
      </div>
    </section>
  )
}
