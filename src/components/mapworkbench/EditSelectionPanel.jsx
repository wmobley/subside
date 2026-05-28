export function EditSelectionPanel({ controls, viewState, selectionMode, setViewState }) {
  return (
    <section className="control-panel">
      <h3>Edit Selection</h3>
      <label htmlFor="rate-mode">Rate mode</label>
      <select
        id="rate-mode"
        value={viewState.rateMode}
        onChange={(event) => setViewState((current) => ({ ...current, rateMode: event.target.value }))}
      >
        <option value="set">Set</option>
        <option value="scale_percent">Scale (%)</option>
      </select>

      <label htmlFor="new-rate">New rate</label>
      <input
        id="new-rate"
        type="number"
        value={viewState.newRate}
        onChange={(event) => setViewState((current) => ({ ...current, newRate: Number(event.target.value) }))}
      />

      <label htmlFor="layers">Layers</label>
      <select
        id="layers"
        multiple
        value={viewState.layers.map(String)}
        onChange={(event) => setViewState((current) => ({
          ...current,
          layers: [...event.target.selectedOptions].map((option) => Number(option.value)),
        }))}
        disabled={viewState.fluxSource === 'rch'}
      >
        {(controls.layerOptions || []).map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>

      <label className="checkbox-row" htmlFor="add-missing">
        <input
          id="add-missing"
          type="checkbox"
          checked={viewState.addMissing}
          disabled={viewState.fluxSource === 'rch'}
          onChange={(event) => setViewState((current) => ({ ...current, addMissing: event.target.checked }))}
        />
        <span>Add missing wells</span>
      </label>

      <div className="selection-strip">
        <span>{selectionMode === 'category' ? 'Category selection' : 'Click markers to select'}</span>
        <button
          className="portal-btn portal-btn-outline portal-btn-sm"
          type="button"
          onClick={() => setViewState((current) => ({ ...current, selectedIds: [] }))}
        >
          Clear
        </button>
      </div>
    </section>
  )
}
