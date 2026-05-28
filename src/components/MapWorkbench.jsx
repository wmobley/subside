import { DatasetPanel } from './mapworkbench/DatasetPanel'
import { EditSelectionPanel } from './mapworkbench/EditSelectionPanel'
import { MapControlsPanel } from './mapworkbench/MapControlsPanel'
import { ModelMap } from './mapworkbench/ModelMap'
import { PublishPanel } from './mapworkbench/PublishPanel'

export function MapWorkbench({ data, state, derived, actions }) {
  const { datasets, dataset, loaded, mapData, controls, summary, suggestions, publishForm } = data
  const { viewState, selectionMode, zoom, isLoading, statusMessage, workflowRun, jwtToken } = state
  const { colorOptions, periodSummary, selectedSet } = derived
  const {
    setDataset,
    setViewState,
    setZoom,
    loadCategorySelection,
    updateForm,
    handleApply,
    toggleSelected,
  } = actions

  return (
    <section className="map-section" id="map">
      <div className="map-header">
        <div>
          <h2>Interactive Map</h2>
          <p>{loaded?.title || 'MODFLOW WEL/RCH visualization and update workbench'}</p>
        </div>
        <div className="map-tools" aria-label="Map status">
          <span className="map-tool">{isLoading ? 'Refreshing' : 'Ready'}</span>
          <span className="map-tool">{summary.activeCellCount} cells</span>
          <span className="map-tool">{viewState.selectedIds.length} selected</span>
        </div>
      </div>

      <div className="map-workbench">
        <aside className="map-controls">
          <DatasetPanel
            datasets={datasets}
            dataset={dataset}
            setDataset={setDataset}
            summary={summary}
            selectedCount={viewState.selectedIds.length}
          />
          <MapControlsPanel
            loaded={loaded}
            controls={controls}
            viewState={viewState}
            colorOptions={colorOptions}
            periodSummary={periodSummary}
            setViewState={setViewState}
            loadCategorySelection={loadCategorySelection}
          />
          <EditSelectionPanel
            controls={controls}
            viewState={viewState}
            selectionMode={selectionMode}
            setViewState={setViewState}
          />
          <PublishPanel
            suggestions={suggestions}
            viewState={viewState}
            setViewState={setViewState}
            publishForm={publishForm}
            updateForm={updateForm}
            jwtToken={jwtToken}
            handleApply={handleApply}
          />
        </aside>

        <ModelMap
          mapData={mapData}
          zoom={zoom}
          setZoom={setZoom}
          selectedSet={selectedSet}
          colorBy={viewState.colorBy}
          toggleSelected={toggleSelected}
        />
      </div>

      <div className="status-ribbon">
        {statusMessage || 'Use category selection or click map markers, then submit an update directly or through a configured Tapis Workflow.'}
        {workflowRun ? ` Workflow run ${workflowRun.runId} is active.` : ''}
      </div>
    </section>
  )
}
