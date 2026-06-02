export function WorkflowModal({
  workflowGroupId,
  workflowStatus,
  onWorkflowGroupChange,
  onRegister,
  onClose,
}) {
  return (
    <div className="workflow-modal-backdrop" role="presentation">
      <div className="workflow-modal" role="dialog" aria-modal="true" aria-labelledby="workflow-modal-title">
        <div className="workflow-modal-head">
          <h2 id="workflow-modal-title">Register Workflow</h2>
          <button className="modal-close" type="button" aria-label="Close workflow registration" onClick={onClose}>x</button>
        </div>
        <p>Enter the workflow group you want this app to use. The backend will create the pipeline there if it does not exist yet.</p>
        <form onSubmit={onRegister}>
          <label htmlFor="workflow-group-id">Workflow group id</label>
          <input
            id="workflow-group-id"
            value={workflowGroupId}
            onChange={(event) => onWorkflowGroupChange(event.target.value)}
            placeholder="your-workflow-group"
          />
          <button className="portal-btn" type="submit" disabled={!workflowGroupId.trim()}>Register Workflow</button>
        </form>
        <div className="portal-note">{workflowStatus || 'This only needs to be done once per workflow group.'}</div>
      </div>
    </div>
  )
}
