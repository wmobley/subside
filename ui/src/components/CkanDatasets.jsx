import { useEffect, useMemo, useState } from 'react'
import { REGION_PRESETS, fetchSubsideDatasets, filterDatasets, getActiveBbox, getFilterOptions } from '../ckan'
import { DatasetFilters } from './datasets/DatasetFilters'
import { DatasetResults } from './datasets/DatasetResults'

const EMPTY_FILTERS = {
  query: '',
  format: '',
  tag: '',
  region: '',
  minLon: '',
  minLat: '',
  maxLon: '',
  maxLat: '',
  requireSpatial: false,
}

export function CkanDatasets() {
  const [datasets, setDatasets] = useState([])
  const [catalogCount, setCatalogCount] = useState(0)
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [status, setStatus] = useState('Loading CKAN datasets...')

  useEffect(() => {
    fetchSubsideDatasets()
      .then((payload) => {
        setDatasets(payload.datasets)
        setCatalogCount(payload.count)
        setStatus('')
      })
      .catch((error) => setStatus(error.message))
  }, [])

  const options = useMemo(() => getFilterOptions(datasets), [datasets])
  const activeBbox = useMemo(() => getActiveBbox(filters), [filters])
  const selectedRegion = useMemo(() => REGION_PRESETS.find((region) => region.value === filters.region), [filters.region])
  const extentLabel = filters.region === 'custom' ? 'Custom extent' : selectedRegion?.label || ''
  const filteredDatasets = useMemo(() => filterDatasets(datasets, filters), [datasets, filters])

  function updateFilter(key, value) {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  function updateRegion(value) {
    setFilters((current) => ({
      ...current,
      region: value,
      minLon: value === 'custom' ? current.minLon : '',
      minLat: value === 'custom' ? current.minLat : '',
      maxLon: value === 'custom' ? current.maxLon : '',
      maxLat: value === 'custom' ? current.maxLat : '',
    }))
  }

  function applyBbox(bbox) {
    setFilters((current) => ({
      ...current,
      region: 'custom',
      minLon: bbox[0].toFixed(4),
      minLat: bbox[1].toFixed(4),
      maxLon: bbox[2].toFixed(4),
      maxLat: bbox[3].toFixed(4),
    }))
  }

  function clearBbox() {
    setFilters((current) => ({
      ...current,
      region: '',
      minLon: '',
      minLat: '',
      maxLon: '',
      maxLat: '',
    }))
  }

  return (
    <section className="ckan-browser">
      <div className="ckan-browser-head">
        <div>
          <h2>TWDB SUBSIDE Catalog</h2>
          <p>{catalogCount || datasets.length} datasets from the CKAN `twdb-subside` organization.</p>
        </div>
        <a className="portal-btn portal-btn-outline" href="https://ckan.tacc.utexas.edu/organization/twdb-subside" target="_blank" rel="noreferrer">
          Open CKAN
        </a>
      </div>

      <DatasetFilters
        filters={filters}
        options={options}
        activeBbox={activeBbox}
        extentLabel={extentLabel}
        onFilterChange={updateFilter}
        onRegionChange={updateRegion}
        onBboxApply={applyBbox}
        onBboxClear={clearBbox}
        onReset={() => setFilters(EMPTY_FILTERS)}
      />

      <div className="dataset-results-summary">
        <strong>{filteredDatasets.length}</strong> matching datasets
        {activeBbox ? <span> bbox: {activeBbox.map((value) => value.toFixed(2)).join(', ')}</span> : null}
      </div>

      {status ? <div className="portal-note">{status}</div> : null}

      <DatasetResults
        datasets={filteredDatasets}
        onTagSelect={(tag) => updateFilter('tag', tag)}
        onFormatSelect={(format) => updateFilter('format', format)}
      />
    </section>
  )
}
