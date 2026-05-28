export function MapControlsPanel({
  loaded,
  controls,
  viewState,
  colorOptions,
  periodSummary,
  setViewState,
  loadCategorySelection,
}) {
  return (
    <section className="control-panel">
      <h3>Map Controls</h3>
      <label htmlFor="flux-source">Flux source</label>
      <select
        id="flux-source"
        value={viewState.fluxSource}
        onChange={(event) => setViewState((current) => ({ ...current, fluxSource: event.target.value }))}
      >
        <option value="wel">Well</option>
        <option value="rch" disabled={!loaded?.hasRch}>Recharge</option>
      </select>

      <label htmlFor="color-by">Color by</label>
      <select
        id="color-by"
        value={viewState.colorBy}
        onChange={(event) => setViewState((current) => ({ ...current, colorBy: event.target.value, categoryValue: '' }))}
      >
        {colorOptions.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>

      {viewState.colorBy === 'flux' ? (
        <>
          <label htmlFor="color-period">Color period</label>
          <select
            id="color-period"
            value={viewState.colorPeriod}
            onChange={(event) => setViewState((current) => ({ ...current, colorPeriod: Number(event.target.value) }))}
          >
            {(controls.colorPeriodOptions || []).map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </>
      ) : (
        <>
          <label htmlFor="category-value">Category</label>
          <select
            id="category-value"
            value={viewState.categoryValue}
            onChange={(event) => setViewState((current) => ({ ...current, categoryValue: event.target.value }))}
          >
            <option value="">Select category</option>
            {(controls.categoryOptions || []).map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <button className="portal-btn portal-btn-sm" type="button" onClick={loadCategorySelection}>Select category</button>
        </>
      )}

      <label htmlFor="stress-periods">Stress periods</label>
      <select
        id="stress-periods"
        multiple
        value={viewState.periods.map(String)}
        onChange={(event) => setViewState((current) => ({
          ...current,
          periods: [...event.target.selectedOptions].map((option) => Number(option.value)),
        }))}
      >
        {(controls.periodOptions || []).map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
      <div className="portal-note">{periodSummary}</div>
    </section>
  )
}
