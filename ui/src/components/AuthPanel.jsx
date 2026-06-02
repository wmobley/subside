export function AuthPanel({
  jwtToken,
  tapisUsername,
  workflowRegistered,
  workflowGroupId,
  loginForm,
  loginStatus,
  onLoginFormChange,
  onLogin,
}) {
  return (
    <aside className="portal-auth-panel" id="api">
      <h3>Tapis Workflow Access</h3>
      {jwtToken ? (
        <>
          <p className="auth-summary">Authenticated as {tapisUsername}</p>
          {workflowRegistered && workflowGroupId ? <p className="auth-meta">Workflow group: {workflowGroupId}</p> : null}
        </>
      ) : (
        <form className="login-form" onSubmit={onLogin}>
          <label htmlFor="login-username">Username</label>
          <input
            id="login-username"
            value={loginForm.username}
            onChange={(event) => onLoginFormChange((current) => ({ ...current, username: event.target.value }))}
            placeholder="Tapis username"
          />
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            value={loginForm.password}
            onChange={(event) => onLoginFormChange((current) => ({ ...current, password: event.target.value }))}
            placeholder="Tapis password"
          />
          <button className="portal-btn" type="submit">Login</button>
        </form>
      )}
      <div className="portal-note">{loginStatus || 'Workflow dispatch is enabled when a Tapis token is present.'}</div>
    </aside>
  )
}
