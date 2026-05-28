export function DataSection({
  modeConfig,
  activeTab,
  onTabChange,
}) {
  return (
    <section className="data-section">
      <div className="tabs" role="tablist" aria-label={`${modeConfig.label} data views`}>
        {modeConfig.tabs.map((tab, index) => (
          <button
            className={`tab ${activeTab === index ? 'active' : ''}`}
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === index}
            onClick={() => onTabChange(index)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="tab-content">
        <div className="dataset-list">
          {modeConfig.datasets.map((item) => (
            <article className="dataset" key={item.title}>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              <div className="tags">
                {item.tags.map((tag) => (
                  <span className="tag" key={tag}>{tag}</span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
