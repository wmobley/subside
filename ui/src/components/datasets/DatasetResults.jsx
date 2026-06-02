export function DatasetResults({ datasets, onTagSelect, onFormatSelect }) {
  return (
    <div className="ckan-dataset-list">
      {datasets.map((dataset) => (
        <article className="ckan-dataset-card" key={dataset.id}>
          <div className="ckan-dataset-card__body">
            <h3><a href={dataset.url} target="_blank" rel="noreferrer">{dataset.title}</a></h3>
            <p>{dataset.notes || 'No dataset description provided.'}</p>
            <div className="dataset-card-meta">
              <span>{dataset.resourceCount} resources</span>
              <span>{dataset.license}</span>
              <span>{dataset.bbox ? 'Spatial extent' : 'No spatial extent'}</span>
            </div>
            <div className="tags">
              {dataset.tags.slice(0, 8).map((tag) => (
                <button className="tag tag-button" key={tag} type="button" onClick={() => onTagSelect(tag)}>{tag}</button>
              ))}
            </div>
          </div>
          <div className="format-list">
            {dataset.formats.slice(0, 12).map((format) => (
              <button className="format-chip" key={format} type="button" onClick={() => onFormatSelect(format)}>{format}</button>
            ))}
          </div>
        </article>
      ))}
    </div>
  )
}
