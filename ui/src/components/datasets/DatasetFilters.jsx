import { REGION_PRESETS } from '../../ckan'
import { SpatialFilterMap } from './SpatialFilterMap'

export function DatasetFilters({
  filters,
  options,
  activeBbox,
  extentLabel,
  onFilterChange,
  onRegionChange,
  onBboxApply,
  onBboxClear,
  onReset,
}) {
  return (
    <div className="dataset-query-panel">
      <div className="query-field query-field-wide">
        <label htmlFor="ckan-query">Search</label>
        <input
          id="ckan-query"
          value={filters.query}
          onChange={(event) => onFilterChange('query', event.target.value)}
          placeholder="Aquifer, county, model name, resource..."
          type="search"
        />
      </div>

      <div className="query-field">
        <label htmlFor="ckan-format">Format</label>
        <select id="ckan-format" value={filters.format} onChange={(event) => onFilterChange('format', event.target.value)}>
          <option value="">Any format</option>
          {options.formats.map((format) => (
            <option key={format} value={format}>{format}</option>
          ))}
        </select>
      </div>

      <div className="query-field">
        <label htmlFor="ckan-tag">Tag</label>
        <select id="ckan-tag" value={filters.tag} onChange={(event) => onFilterChange('tag', event.target.value)}>
          <option value="">Any tag</option>
          {options.tags.map((tag) => (
            <option key={tag} value={tag}>{tag}</option>
          ))}
        </select>
      </div>

      <div className="query-field">
        <label htmlFor="ckan-region">Spatial filter</label>
        <select id="ckan-region" value={filters.region} onChange={(event) => onRegionChange(event.target.value)}>
          {REGION_PRESETS.map((region) => (
            <option key={region.value || 'all'} value={region.value}>{region.label}</option>
          ))}
        </select>
      </div>

      {filters.region === 'custom' ? (
        <div className="bbox-grid" aria-label="Custom bounding box">
          <input value={filters.minLon} onChange={(event) => onFilterChange('minLon', event.target.value)} placeholder="Min lon" inputMode="decimal" />
          <input value={filters.minLat} onChange={(event) => onFilterChange('minLat', event.target.value)} placeholder="Min lat" inputMode="decimal" />
          <input value={filters.maxLon} onChange={(event) => onFilterChange('maxLon', event.target.value)} placeholder="Max lon" inputMode="decimal" />
          <input value={filters.maxLat} onChange={(event) => onFilterChange('maxLat', event.target.value)} placeholder="Max lat" inputMode="decimal" />
        </div>
      ) : null}

      <SpatialFilterMap bbox={activeBbox} extentLabel={extentLabel} onBboxChange={onBboxApply} onBboxClear={onBboxClear} />

      <label className="checkbox-row" htmlFor="ckan-spatial-only">
        <input
          id="ckan-spatial-only"
          type="checkbox"
          checked={filters.requireSpatial}
          onChange={(event) => onFilterChange('requireSpatial', event.target.checked)}
        />
        <span>Only datasets with spatial metadata</span>
      </label>

      <button className="portal-btn portal-btn-outline portal-btn-sm" type="button" onClick={onReset}>
        Reset filters
      </button>
    </div>
  )
}
