import { startTransition, useDeferredValue, useEffect, useMemo, useState } from 'react'
import 'leaflet/dist/leaflet.css'

import { requestJson } from './api'
import { PortalPageContent } from './components/pages/PortalPageContent'
import { PortalHeader } from './components/PortalChrome'
import { WorkflowModal } from './components/WorkflowModal'
import { PORTAL_CONFIGS } from './config'
import { EMPTY_FORM, buildSuggestedFields, summarizePeriods } from './modeling'

export default function App() {
  const [activePage, setActivePage] = useState('home')
  const [portalMode, setPortalMode] = useState('public')
  const [searchTerm, setSearchTerm] = useState('')
  const [datasets, setDatasets] = useState([])
  const [dataset, setDataset] = useState('')
  const [loaded, setLoaded] = useState(null)
  const [mapData, setMapData] = useState({ center: { lat: 30.26, lon: -97.74, zoom: 8 }, cells: [] })
  const [controls, setControls] = useState({ periodOptions: [], layerOptions: [], categoryOptions: [] })
  const [summary, setSummary] = useState({ selectedCount: 0, activeCellCount: 0, fluxSource: 'wel' })
  const [jwtToken, setJwtToken] = useState('')
  const [tapisUsername, setTapisUsername] = useState('')
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [loginStatus, setLoginStatus] = useState('')
  const [statusMessage, setStatusMessage] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [selectionMode, setSelectionMode] = useState('manual')
  const [zoom, setZoom] = useState(8)
  const [isLoading, setIsLoading] = useState(false)
  const [formTouched, setFormTouched] = useState(false)
  const [workflowRun, setWorkflowRun] = useState(null)
  const [workflowGroupId, setWorkflowGroupId] = useState('')
  const [workflowRegistered, setWorkflowRegistered] = useState(false)
  const [showWorkflowModal, setShowWorkflowModal] = useState(false)
  const [workflowStatus, setWorkflowStatus] = useState('')
  const [viewState, setViewState] = useState({
    fluxSource: 'wel',
    colorBy: 'flux',
    colorPeriod: '',
    periods: [],
    layers: [1],
    rateMode: 'set',
    newRate: -20,
    addMissing: false,
    categoryValue: '',
    selectedIds: [],
    datasetSuggestion: '',
  })
  const [publishForm, setPublishForm] = useState(EMPTY_FORM)

  const deferredSelectedIds = useDeferredValue(viewState.selectedIds)
  const modeConfig = PORTAL_CONFIGS[portalMode]
  const selectedSet = useMemo(() => new Set(viewState.selectedIds), [viewState.selectedIds])
  const periodSummary = useMemo(() => summarizePeriods(viewState.periods, controls.periodOptions || []), [viewState.periods, controls.periodOptions])
  const colorOptions = controls.colorOptions?.length ? controls.colorOptions : [{ value: 'flux', label: 'Flux' }]

  useEffect(() => {
    requestJson('/api/datasets')
      .then((payload) => {
        setDatasets(payload.datasets || [])
        if (payload.datasets?.length) setDataset(payload.datasets[0].value)
      })
      .catch((error) => setStatusMessage(error.message))
  }, [])

  useEffect(() => {
    if (!tapisUsername || !jwtToken) {
      setSuggestions([{ label: 'New dataset', value: '__new__' }])
      return
    }
    requestJson(`/api/dataset-suggestions?username=${encodeURIComponent(tapisUsername)}&jwtToken=${encodeURIComponent(jwtToken)}`)
      .then((payload) => setSuggestions(payload.options || []))
      .catch(() => setSuggestions([{ label: 'New dataset', value: '__new__' }]))
  }, [jwtToken, tapisUsername])

  useEffect(() => {
    if (!loaded || formTouched) return
    setPublishForm(buildSuggestedFields(loaded, controls, viewState))
  }, [loaded, controls, viewState, formTouched])

  useEffect(() => {
    if (!workflowRun || !jwtToken) return undefined
    const interval = window.setInterval(() => {
      requestJson(
        `/api/workflow-runs/${encodeURIComponent(workflowRun.groupId)}/${encodeURIComponent(workflowRun.pipelineId)}/${encodeURIComponent(workflowRun.runId)}?jwtToken=${encodeURIComponent(jwtToken)}`,
      )
        .then((payload) => {
          const normalizedStatus = String(payload.status || '').toUpperCase()
          if (['COMPLETED', 'COMPLETE', 'SUCCESS', 'SUCCEEDED'].includes(normalizedStatus)) {
            const resultMessage = payload.result?.message || `Workflow run ${workflowRun.runId} completed.`
            setStatusMessage(resultMessage)
            setWorkflowRun(null)
          } else if (['FAILED', 'ERROR', 'CANCELED', 'CANCELLED'].includes(normalizedStatus)) {
            setStatusMessage(payload.result?.message || `Workflow run ${workflowRun.runId}: ${payload.status}`)
            setWorkflowRun(null)
          } else {
            setStatusMessage(`Workflow run ${workflowRun.runId}: ${payload.status}`)
          }
        })
        .catch((error) => {
          setStatusMessage(error.message)
          setWorkflowRun(null)
        })
    }, 4000)
    return () => window.clearInterval(interval)
  }, [workflowRun, jwtToken])

  useEffect(() => {
    if (!dataset) return
    setIsLoading(true)
    const params = new URLSearchParams({
      fluxSource: viewState.fluxSource,
      colorBy: viewState.colorBy,
    })
    if (viewState.colorPeriod !== '') params.set('colorPeriod', String(viewState.colorPeriod))
    if (viewState.periods.length) params.set('periods', viewState.periods.join(','))
    requestJson(`/api/datasets/${encodeURIComponent(dataset)}/view?${params.toString()}`)
      .then((payload) => {
        setLoaded(payload.dataset)
        setControls(payload.controls)
        setSummary({ ...payload.summary, selectedCount: deferredSelectedIds.length })
        setMapData(payload.mapData)
        setStatusMessage('')
        startTransition(() => {
          setViewState((current) => {
            const nextPeriods = current.periods.length ? current.periods : payload.controls.periodOptions.slice(0, 1).map((option) => option.value)
            const nextLayers = current.layers.length ? current.layers : payload.controls.layerOptions.slice(0, 1).map((option) => option.value)
            const nextColorPeriod =
              current.colorPeriod !== '' ? current.colorPeriod : payload.controls.colorPeriodOptions?.[0]?.value ?? ''
            return { ...current, periods: nextPeriods, layers: nextLayers, colorPeriod: nextColorPeriod }
          })
          if (payload.mapData?.center?.zoom) setZoom(payload.mapData.center.zoom)
        })
      })
      .catch((error) => setStatusMessage(error.message))
      .finally(() => setIsLoading(false))
  }, [dataset, viewState.fluxSource, viewState.colorBy, viewState.colorPeriod, viewState.periods, deferredSelectedIds.length])

  function updateForm(key, value) {
    setFormTouched(true)
    setPublishForm((current) => ({ ...current, [key]: value }))
  }

  function handlePortalSearch(event) {
    event.preventDefault()
    const query = searchTerm.trim()
    if (!query) {
      setStatusMessage(`Enter a search term for ${modeConfig.label.toLowerCase()} mode.`)
      return
    }
    setStatusMessage(`Searching "${query}" in ${modeConfig.label.toLowerCase()} mode.`)
  }

  async function loadCategorySelection() {
    if (!dataset || !viewState.categoryValue || viewState.colorBy === 'flux') return
    const payload = await requestJson(`/api/datasets/${encodeURIComponent(dataset)}/category-selection`, {
      method: 'POST',
      body: JSON.stringify({ colorBy: viewState.colorBy, categoryValue: viewState.categoryValue }),
    })
    setSelectionMode('category')
    setViewState((current) => ({ ...current, selectedIds: payload.selectedIds || [] }))
  }

  async function handleLogin(event) {
    event.preventDefault()
    setLoginStatus('Authenticating...')
    try {
      const payload = await requestJson('/api/login', {
        method: 'POST',
        body: JSON.stringify(loginForm),
      })
      setJwtToken(payload.jwtToken)
      setTapisUsername(payload.username)
      setLoginStatus(`Logged in as ${payload.username}`)
      setWorkflowRegistered(false)
      setWorkflowStatus('')
      setShowWorkflowModal(true)
    } catch (error) {
      setLoginStatus(error.message)
    }
  }

  async function handleWorkflowRegister(event) {
    event?.preventDefault?.()
    setWorkflowStatus('Registering workflow...')
    try {
      const payload = await requestJson('/api/workflow/register', {
        method: 'POST',
        body: JSON.stringify({
          jwtToken,
          workflowGroupId,
        }),
      })
      setWorkflowGroupId(payload.groupId)
      setWorkflowRegistered(true)
      setWorkflowStatus(payload.message)
      setShowWorkflowModal(false)
      setStatusMessage(payload.message)
    } catch (error) {
      setWorkflowRegistered(false)
      setWorkflowStatus(error.message)
    }
  }

  async function handleApply() {
    try {
      const payload = await requestJson('/api/apply', {
        method: 'POST',
        body: JSON.stringify({
          dataset,
          selectedIds: viewState.selectedIds,
          fluxSource: viewState.fluxSource,
          newRate: Number(viewState.newRate),
          rateMode: viewState.rateMode,
          addMissing: viewState.addMissing,
          layers: viewState.layers,
          periods: viewState.periods,
          jwtToken,
          tapisUsername,
          workflowGroupId,
          ...publishForm,
        }),
      })
      if (payload.mode === 'workflow') {
        setWorkflowRun({ groupId: payload.groupId, pipelineId: payload.pipelineId, runId: payload.runId })
      }
      setStatusMessage(payload.message)
    } catch (error) {
      setStatusMessage(error.message)
    }
  }

  function toggleSelected(cellId) {
    setSelectionMode('manual')
    setViewState((current) => {
      const exists = current.selectedIds.includes(cellId)
      return {
        ...current,
        selectedIds: exists ? current.selectedIds.filter((value) => value !== cellId) : [...current.selectedIds, cellId],
      }
    })
  }

  const authProps = {
    jwtToken,
    tapisUsername,
    workflowRegistered,
    workflowGroupId,
    loginForm,
    loginStatus,
    onLoginFormChange: setLoginForm,
    onLogin: handleLogin,
  }

  const mapWorkbenchProps = {
    data: { datasets, dataset, loaded, mapData, controls, summary, suggestions, publishForm },
    state: { viewState, selectionMode, zoom, isLoading, statusMessage, workflowRun, jwtToken },
    derived: { colorOptions, periodSummary, selectedSet },
    actions: {
      setDataset,
      setViewState,
      setZoom,
      loadCategorySelection,
      updateForm,
      handleApply,
      toggleSelected,
    },
  }

  return (
    <div className="subside-page">
      <PortalHeader
        activePage={activePage}
        portalMode={portalMode}
        onPageChange={setActivePage}
        onModeChange={setPortalMode}
      />
      <PortalPageContent
        activePage={activePage}
        modeConfig={modeConfig}
        portalMode={portalMode}
        searchTerm={searchTerm}
        onSearchTermChange={setSearchTerm}
        onSearch={handlePortalSearch}
        onModeChange={setPortalMode}
        authProps={authProps}
        mapWorkbenchProps={mapWorkbenchProps}
      />

      {showWorkflowModal ? (
        <WorkflowModal
          workflowGroupId={workflowGroupId}
          workflowStatus={workflowStatus}
          onWorkflowGroupChange={setWorkflowGroupId}
          onRegister={handleWorkflowRegister}
          onClose={() => setShowWorkflowModal(false)}
        />
      ) : null}
    </div>
  )
}
