const uploadForm = document.getElementById('uploadForm')
const fileInput = document.getElementById('fileInput')
const passwordInput = document.getElementById('passwordInput')
const jobsList = document.getElementById('jobs')
const logEl = document.getElementById('log')
const statusEl = document.getElementById('status')
const jobDetailEl = document.getElementById('jobDetail')
const statsEl = document.getElementById('stats')
const logSectionEl = document.getElementById('log-section')
const statsSectionEl = document.getElementById('stats-section')
const detailSectionEl = document.getElementById('detail-section')
const rollbackDialog = document.getElementById('rollbackDialog')
const backupSelect = document.getElementById('backupSelect')
const rollbackStatusEl = document.getElementById('rollbackStatus')
const logLevelFilterEl = document.getElementById('logLevelFilter')
const servicesListEl = document.getElementById('servicesList')

let currentJobId = null
let logLevelFilter = 'all'  // all, debug, info, warning, error
let allLogEntries = []  // store all entries for filtering
let eventSource = null  // track active event stream

async function refreshJobs() {
  const res = await fetch('/api/jobs')
  const jobs = await res.json()
  jobsList.innerHTML = ''
  jobs.forEach(j => {
    const li = document.createElement('div')
    li.className = 'job-item'
    const statusClass = j.status === 'completed' ? 'success' : j.status === 'failed' ? 'error' : 'running'
    li.innerHTML = `
      <span class="job-status ${statusClass}">${j.status}</span>
      <span class="job-name">${j.name}</span>
      <span class="job-date">${new Date(j.created * 1000).toLocaleString()}</span>
      <button onclick="showJobDetail('${j.id}')">Details</button>
      ${j.backups && j.backups.length > 0 ? `<button onclick="showRollbackDialog('${j.id}')">Rollback</button>` : ''}
      <button onclick="deleteJob('${j.id}')">Delete</button>
    `
    jobsList.appendChild(li)
  })
}

function showJobDetail(jobId) {
  currentJobId = jobId
  detailSectionEl.style.display = 'block'
  logSectionEl.style.display = 'block'
  statsSectionEl.style.display = 'block'
  logLevelFilter = 'all'
  if (logLevelFilterEl) logLevelFilterEl.value = 'all'

  fetch(`/api/job/${jobId}`)
    .then(r => r.json())
    .then(j => {
      jobDetailEl.innerHTML = `
        <table class="detail-table">
          <tr><td>ID:</td><td><code>${j.id}</code></td></tr>
          <tr><td>Name:</td><td>${j.name}</td></tr>
          <tr><td>Status:</td><td><span class="badge ${j.status}">${j.status}</span></td></tr>
          <tr><td>Created:</td><td>${new Date(j.created * 1000).toLocaleString()}</td></tr>
          <tr><td>Backups:</td><td>${j.backups.length}</td></tr>
          ${j.backups.length > 0 ? `<tr><td>Latest Backup:</td><td>${j.backups[j.backups.length - 1].name}</td></tr>` : ''}
        </table>
      `

      // Display file statistics if available
      if (j.stats && Object.keys(j.stats).length > 0) {
        let statsHtml = '<h3>Generated Files</h3><table class="stats-table"><tr><th>File</th><th>Before</th><th>After</th><th>Change</th><th>Diff</th><th>Action</th></tr>'
        for (const [fname, stat] of Object.entries(j.stats)) {
          const deltaClass = stat.delta > 0 ? 'positive' : stat.delta < 0 ? 'negative' : 'neutral'
          const deltaStr = stat.delta >= 0 ? `+${stat.delta}` : `${stat.delta}`

          // Detailed diff info
          let diffHtml = ''
          if (stat.added !== undefined) {
            if (stat.added > 0) diffHtml += `<span class="badge success" style="margin-right:5px">+${stat.added}</span>`
            if (stat.removed > 0) diffHtml += `<span class="badge error">-${stat.removed}</span>`
            if (stat.added === 0 && stat.removed === 0) diffHtml = '<span class="neutral">-</span>'
          } else {
            diffHtml = '<span class="neutral">-</span>'
          }

          // Escape backslashes for HTML onclick attribute (double escape needed)
          const escapedFname = fname.replace(/\\/g, '\\\\')
          statsHtml += `<tr><td>${fname}</td><td>${stat.before}</td><td>${stat.after}</td><td class="${deltaClass}">${deltaStr}</td><td>${diffHtml}</td><td><button onclick="previewFile('${escapedFname}')">Preview</button></td></tr>`
        }
        statsHtml += '</table>'
        if (statsEl) statsEl.innerHTML = statsHtml
      } else {
        if (statsEl) statsEl.innerHTML = ''
      }

      // Load stored log entries from job.log
      if (j.log && j.log.length > 0) {
        // Convert logs to consistent format if needed
        allLogEntries = j.log.map(entry => {
          if (typeof entry === 'string') {
            // Old format: just a string
            return { level: 'info', text: entry }
          } else if (typeof entry === 'object' && entry.text) {
            // New format: {level, text}
            return { level: entry.level || 'info', text: entry.text }
          }
          return { level: 'info', text: String(entry) }
        })
        renderLog()
      } else {
        allLogEntries = []
        if (j.status !== 'running') {
          logEl.textContent = 'No logs available'
        }
      }

      // If job is still running, start streaming events
      if (j.status === 'running') {
        startEvents(jobId)
      }
    })
}

function showRollbackDialog(jobId) {
  currentJobId = jobId
  fetch(`/api/job/${jobId}`)
    .then(r => r.json())
    .then(j => {
      backupSelect.innerHTML = ''
      j.backups.forEach(b => {
        const opt = document.createElement('option')
        opt.value = b.name
        opt.textContent = b.name + ' (' + b.ts + ')'
        backupSelect.appendChild(opt)
      })
      rollbackDialog.showModal()
    })
}

async function deleteJob(jobId) {
  if (!confirm('Delete this job from history?')) return
  try {
    const res = await fetch(`/api/job/${jobId}`, { method: 'DELETE' })
    if (res.ok) {
      refreshJobs()
      detailSectionEl.style.display = 'none'
      logSectionEl.style.display = 'none'
      statsSectionEl.style.display = 'none'
    } else {
      alert('Delete failed')
    }
  } catch (e) {
    alert('Error: ' + e.message)
  }
}

async function doRollback() {
  const backup = backupSelect.value
  rollbackStatusEl.textContent = 'Rolling back...'
  try {
    const res = await fetch(`/api/job/${currentJobId}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backup })
    })
    const data = await res.json()
    if (data.ok) {
      rollbackStatusEl.textContent = '✓ Rollback successful: ' + data.output
      setTimeout(() => rollbackDialog.close(), 2000)
    } else {
      rollbackStatusEl.textContent = '✗ Error: ' + data.error
    }
  } catch (e) {
    rollbackStatusEl.textContent = '✗ Error: ' + e.message
  }
}

async function restartService(service) {
  const btn = event.target
  btn.disabled = true
  btn.textContent = 'Restarting...'
  try {
    const res = await fetch('/api/service/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service })
    })
    const data = await res.json()
    if (data.ok) {
      btn.textContent = 'Restart'
      // Refresh service status after restart
      refreshServices()
    } else {
      btn.textContent = 'Restart'
      alert('Error: ' + data.output)
    }
  } catch (e) {
    btn.textContent = 'Restart'
    alert('Error: ' + e.message)
  }
  btn.disabled = false
}

let currentPreviewData = null  // Store current preview data for view switching

async function previewFile(filename) {
  try {
    // Normalize path separators (backslash to forward slash) for cross-platform compatibility
    const normalizedPath = filename.replace(/\\/g, '/')

    // Show loading state and reset UI
    const dialog = document.getElementById('filePreviewDialog')
    const content = document.getElementById('previewContent')
    const diffContent = document.getElementById('diffContent')
    const title = document.getElementById('previewFileName')
    const finalBtn = document.getElementById('viewModeFinal')
    const diffBtn = document.getElementById('viewModeDiff')
    const legend = document.getElementById('diffLegend')

    // Reset to final view state
    title.textContent = filename
    content.textContent = 'Loading...'
    content.style.display = 'block'
    diffContent.innerHTML = ''
    diffContent.style.display = 'none'
    legend.style.display = 'none'
    finalBtn.classList.add('active')
    diffBtn.classList.remove('active')

    dialog.showModal()

    // Fetch current file content
    const res = await fetch(`/api/file/preview?path=openhab/${normalizedPath}`)
    if (!res.ok) {
      const error = await res.json()
      throw new Error(error.error || 'Failed to load file')
    }
    const data = await res.json()

    // Try to fetch original file from backup (if available for current job)
    let originalData = null
    if (currentJobId) {
      const jobRes = await fetch(`/api/job/${currentJobId}`)
      if (jobRes.ok) {
        const job = await jobRes.json()
        if (job.backups && job.backups.length > 0) {
          // Get the latest backup (created before job ran)
          const latestBackup = job.backups[job.backups.length - 1]
          try {
            const backupRes = await fetch(`/api/file/preview?path=openhab/${normalizedPath}&backup=${latestBackup.name}`)
            if (backupRes.ok) {
              originalData = await backupRes.json()
            }
          } catch (e) {
            // Original file might not exist in backup (new file)
            console.log('Original file not found in backup:', e)
          }
        }
      }
    }



    // Fetch diff from backend
    let diffData = null
    if (currentJobId) {
      try {
        const diffRes = await fetch(`/api/job/${currentJobId}/file/diff?path=openhab/${normalizedPath}`)
        if (diffRes.ok) {
          diffData = await diffRes.json()
        }
      } catch (e) {
        console.log('Diff fetch failed:', e)
      }
    }

    // Store data for view switching
    currentPreviewData = {
      filename: filename,
      current: data,
      original: originalData,
      diff: diffData
    }

    // Display final view by default
    switchViewMode('final')

    // Add file size info
    if (data.size) {
      const sizeKB = (data.size / 1024).toFixed(2)
      title.textContent = `${filename} (${sizeKB} KB)`
    }
  } catch (e) {
    alert('Error loading file: ' + e.message)
    document.getElementById('filePreviewDialog').close()
  }
}

function switchViewMode(mode) {
  if (!currentPreviewData) return

  const content = document.getElementById('previewContent')
  const diffContent = document.getElementById('diffContent')
  const finalBtn = document.getElementById('viewModeFinal')
  const diffBtn = document.getElementById('viewModeDiff')
  const legend = document.getElementById('diffLegend')

  if (mode === 'final') {
    // Show final view
    content.style.display = 'block'
    diffContent.style.display = 'none'
    legend.style.display = 'none'
    finalBtn.classList.add('active')
    diffBtn.classList.remove('active')

    content.textContent = currentPreviewData.current.content
  } else if (mode === 'diff') {
    // Show diff view
    content.style.display = 'none'
    diffContent.style.display = 'block'
    legend.style.display = 'flex'
    finalBtn.classList.remove('active')
    diffBtn.classList.add('active')

    // Generate diff
    // Generate diff
    let html = ''
    if (currentPreviewData.diff) {
      html = renderBackendDiff(currentPreviewData.diff)
    } else {
      const original = currentPreviewData.original ? currentPreviewData.original.content : ''
      const current = currentPreviewData.current.content
      html = generateDiff(original, current)
    }
    diffContent.innerHTML = html
  }
}

function renderBackendDiff(diffEntries) {
  let html = ''
  for (const entry of diffEntries) {
    const lineClass = entry.type === 'added' ? 'added' :
      entry.type === 'removed' ? 'removed' : 'unchanged'

    const linePrefix = entry.type === 'added' ? '+' :
      entry.type === 'removed' ? '-' : ' '

    const escapedLine = escapeHtml(entry.line)
    const displayLineNum = (entry.type === 'removed') ? '-' : entry.curr_ln

    html += `<div class="diff-line ${lineClass}">` +
      `<span class="diff-line-number">${linePrefix} ${displayLineNum}</span>` +
      `<span class="diff-line-content">${escapedLine}</span>` +
      `</div>`
  }
  return html || '<div class="diff-line unchanged"><span class="diff-line-number"> </span><span class="diff-line-content">(empty diff)</span></div>'
}

function generateDiff(originalText, currentText) {
  const originalLines = originalText.split('\n')
  const currentLines = currentText.split('\n')

  // Simple line-by-line diff algorithm
  const diff = computeLineDiff(originalLines, currentLines)

  // Generate HTML
  let html = ''
  let lineNum = 1

  for (const entry of diff) {
    const lineClass = entry.type === 'added' ? 'added' :
      entry.type === 'removed' ? 'removed' :
        entry.type === 'modified' ? 'modified' : 'unchanged'

    const linePrefix = entry.type === 'added' ? '+' :
      entry.type === 'removed' ? '-' :
        entry.type === 'modified' ? '~' : ' '

    const escapedLine = escapeHtml(entry.line)

    // Only show line numbers for unchanged and added lines (final file)
    const displayLineNum = (entry.type === 'removed') ? '-' : lineNum

    html += `<div class="diff-line ${lineClass}">` +
      `<span class="diff-line-number">${linePrefix} ${displayLineNum}</span>` +
      `<span class="diff-line-content">${escapedLine}</span>` +
      `</div>`

    // Increment line number for non-removed lines
    if (entry.type !== 'removed') {
      lineNum++
    }
  }

  return html || '<div class="diff-line unchanged"><span class="diff-line-number"> </span><span class="diff-line-content">(empty file)</span></div>'
}

function computeLineDiff(original, current) {
  // Simple diff algorithm: find matching and non-matching lines
  const result = []
  const maxLen = Math.max(original.length, current.length)

  let i = 0, j = 0

  while (i < original.length || j < current.length) {
    const origLine = i < original.length ? original[i] : null
    const currLine = j < current.length ? current[j] : null

    if (origLine === null) {
      // Only current line exists (added)
      result.push({ type: 'added', line: currLine })
      j++
    } else if (currLine === null) {
      // Only original line exists (removed)
      result.push({ type: 'removed', line: origLine })
      i++
    } else if (origLine === currLine) {
      // Lines match (unchanged)
      result.push({ type: 'unchanged', line: currLine })
      i++
      j++
    } else {
      // Lines differ - check if it's a modification or add/remove
      // Look ahead to see if current line appears later in original (insertion)
      const currInOrigLater = original.slice(i + 1, i + 5).indexOf(currLine)
      // Look ahead to see if original line appears later in current (deletion)
      const origInCurrLater = current.slice(j + 1, j + 5).indexOf(origLine)

      if (currInOrigLater >= 0 && (origInCurrLater < 0 || currInOrigLater < origInCurrLater)) {
        // Current line appears soon in original - treat as deletion of original lines
        result.push({ type: 'removed', line: origLine })
        i++
      } else if (origInCurrLater >= 0) {
        // Original line appears soon in current - treat as addition
        result.push({ type: 'added', line: currLine })
        j++
      } else {
        // Lines are modified (simple replacement)
        result.push({ type: 'removed', line: origLine })
        result.push({ type: 'added', line: currLine })
        i++
        j++
      }
    }
  }

  return result
}

async function refreshServices() {
  const services = ['openhab.service']
  servicesListEl.innerHTML = ''

  for (const service of services) {
    try {
      const res = await fetch(`/api/service/${service}/status`)
      const status = await res.json()

      const div = document.createElement('div')
      div.className = 'service-item'

      const statusClass = status.active ? 'active' : 'inactive'
      const statusText = status.status.charAt(0).toUpperCase() + status.status.slice(1)

      div.innerHTML = `
        <div class="service-header">
          <span class="service-name">${service}</span>
          <span class="service-status ${statusClass}">${statusText}</span>
        </div>
        <button onclick="restartService('${service}')" class="service-restart-btn">Restart</button>
      `
      servicesListEl.appendChild(div)
    } catch (e) {
      console.error('Error fetching service status:', e)
    }
  }
}

// Log level filtering
if (logLevelFilterEl) {
  logLevelFilterEl.addEventListener('change', (e) => {
    logLevelFilter = e.target.value
    renderLog()
  })
}

function renderLog() {
  let filtered = allLogEntries
  if (logLevelFilter !== 'all') {
    filtered = allLogEntries.filter(entry => entry.level === logLevelFilter)
  }

  // Render with color coding based on log level
  const html = filtered.map(entry => {
    const levelClass = `log-level-${entry.level}`
    return `<div class="log-entry ${levelClass}">${escapeHtml(entry.text)}</div>`
  }).join('')

  logEl.innerHTML = html
  logEl.scrollTop = logEl.scrollHeight
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  }
  return text.replace(/[&<>"']/g, m => map[m])
}

// Configuration Management
async function loadConfig() {
  const configStatus = document.getElementById('configStatus')
  const configJson = document.getElementById('configJson')

  try {
    configStatus.textContent = 'Loading configuration...'
    const res = await fetch('/api/config')
    if (!res.ok) throw new Error('Failed to load config')
    const config = await res.json()
    configJson.value = JSON.stringify(config, null, 2)
    configStatus.textContent = '✓ Configuration loaded'
    configStatus.className = 'status-message success'
  } catch (e) {
    configStatus.textContent = '✗ Error: ' + e.message
    configStatus.className = 'status-message error'
  }
}

async function saveConfig() {
  const configStatus = document.getElementById('configStatus')
  const configJson = document.getElementById('configJson')

  try {
    configStatus.textContent = 'Saving configuration...'
    const config = JSON.parse(configJson.value)
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    })
    if (!res.ok) throw new Error('Failed to save config')
    const result = await res.json()
    configStatus.textContent = '✓ ' + result.message
    configStatus.className = 'status-message success'
  } catch (e) {
    configStatus.textContent = '✗ Error: ' + e.message
    configStatus.className = 'status-message error'
  }
}

// Project Preview
let currentPreviewMetadata = null

async function previewProject() {
  const fileInput = document.getElementById('fileInput')
  const passwordInput = document.getElementById('passwordInput')
  const statusEl = document.getElementById('status')
  const previewSection = document.getElementById('preview-section')

  const f = fileInput.files[0]
  if (!f) {
    alert('Please select a file first')
    return
  }

 const fd = new FormData()
  fd.append('file', f)
 const pwd = passwordInput.value
  if (pwd) {
    fd.append('password', pwd)
  }

  statusEl.textContent = 'Parsing project structure...'
  statusEl.className = 'status-message'

  try {
    const res = await fetch('/api/project/preview', { method: 'POST', body: fd })
    if (!res.ok) {
      const error = await res.json()
      throw new Error(error.error || 'Preview failed')
    }
    const preview = await res.json()

    currentPreviewMetadata = preview.metadata
    displayBuildingPreview(preview)

    // Show preview section
    previewSection.style.display = 'block'

    statusEl.textContent = '✓ Project structure loaded'
    statusEl.className = 'status-message success'

    // Scroll to preview
    previewSection.scrollIntoView({ behavior: 'smooth' })
  } catch (e) {
    statusEl.textContent = '✗ Error: ' + e.message
    statusEl.className = 'status-message error'
  }
}

function displayBuildingPreview(preview) {
  const metadataEl = document.getElementById('previewMetadata')
  const treeEl = document.getElementById('buildingTree')

  // Display metadata
  let metadataHtml = '<div class="metadata-cards">'
  if (preview.metadata.project_name) {
    metadataHtml += `<div class="metadata-card"><strong>Project:</strong> ${escapeHtml(preview.metadata.project_name)}</div>`
  }
  if (preview.metadata.gateway_ip) {
    metadataHtml += `<div class="metadata-card"><strong>Gateway IP:</strong> ${escapeHtml(preview.metadata.gateway_ip)}</div>`
  } else {
    metadataHtml += `<div class="metadata-card gateway-missing"><strong>Gateway IP:</strong> <span class="missing">Not found in project</span></div>`
  }
  metadataHtml += `<div class="metadata-card"><strong>Total Addresses:</strong> ${preview.metadata.total_addresses}</div>`
  metadataHtml += `<div class="metadata-card"><strong>HomeKit:</strong> ${preview.metadata.homekit_enabled ? '✓ Enabled' : '✗ Disabled'}</div>`
  metadataHtml += `<div class="metadata-card"><strong>Alexa:</strong> ${preview.metadata.alexa_enabled ? '✓ Enabled' : '✗ Disabled'}</div>`
  
  // Check for unknown items in metadata
  if (preview.metadata.unknown_items && preview.metadata.unknown_items.length > 0) {
    metadataHtml += `<div class="metadata-card unknown-items"><strong>Unknown Items:</strong> <span class="highlight">${preview.metadata.unknown_items.length} found</span></div>`
  }
  
  metadataHtml += '</div>'
  metadataEl.innerHTML = metadataHtml

  // Display building tree
  let treeHtml = ''
  for (const building of preview.buildings) {
    treeHtml += `<div class="tree-node building-node">
      <div class="tree-node-header" onclick="toggleTreeNode(this)">
        <span class="tree-icon">▶</span>
        <span class="tree-label">🏢 ${escapeHtml(building.name)}</span>
        <span class="tree-count">${building.floors.length} floor(s)</span>
      </div>
      <div class="tree-children" style="display:none;">`

    for (const floor of building.floors) {
      treeHtml += `<div class="tree-node floor-node">
        <div class="tree-node-header" onclick="toggleTreeNode(this)">
          <span class="tree-icon">▶</span>
          <span class="tree-label">🏠 ${escapeHtml(floor.name)}</span>
          <span class="tree-count">${floor.rooms.length} room(s)</span>
        </div>
        <div class="tree-children" style="display:none;">`

      for (const room of floor.rooms) {
        const hasAddresses = room.addresses && room.addresses.length > 0;
        treeHtml += `<div class="tree-node room-node">
          <div class="tree-node-header" onclick="toggleTreeNode(this)">
            <span class="tree-icon">${hasAddresses ? '▶' : '•'}</span>
            <span class="tree-label">🚪 ${escapeHtml(room.name)}</span>
            <span class="tree-count">${room.address_count} address(es), ${room.device_count} device(s)}</span>
          </div>
          ${hasAddresses ? `
          <div class="tree-children" style="display:none;">
            <div class="room-addresses">
              <div class="address-list">
                ${room.addresses.map(addr => `<div class="address-item">${escapeHtml(addr['Group name'])} (${addr.Address})</div>`).join('')}
              </div>
            </div>
          </div>` : ''}
        </div>`
      }

      treeHtml += `</div></div>`
    }

    treeHtml += `</div></div>`
  }

  treeEl.innerHTML = treeHtml
}

function toggleTreeNode(header) {
  const node = header.parentElement
  const children = node.querySelector('.tree-children')
  const icon = header.querySelector('.tree-icon')

  if (children && children.style.display === 'none') {
    children.style.display = 'block'
    icon.textContent = '▼'
  } else if (children) {
    children.style.display = 'none'
    icon.textContent = '▶'
  }
}


function toggleSection(contentId) {
  const content = document.getElementById(contentId)
  const header = content.previousElementSibling
  const icon = header.querySelector('.toggle-icon')

  if (content.style.display === 'none') {
    content.style.display = 'block'
    icon.textContent = '▲'
  } else {
    content.style.display = 'none'
    icon.textContent = '▼'
  }
}

uploadForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  const f = fileInput.files[0]
  if (!f) return alert('select a file')
  const fd = new FormData()
  fd.append('file', f)
  const pwd = passwordInput.value
  if (pwd) {
    fd.append('password', pwd)
  }


  statusEl.textContent = 'Uploading...'
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: fd })
    if (!res.ok) throw new Error('Upload failed: ' + res.status)
    const job = await res.json()
    statusEl.textContent = `Job started: ${job.id}`
    refreshJobs()
    showJobDetail(job.id)
    allLogEntries = []  // Start with empty logs for new upload
    startEvents(job.id)
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`
  }
})


function startEvents(jobId) {
  // Close any existing event source
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }

  // Only clear text if no logs loaded yet
  if (allLogEntries.length === 0) {
    logEl.textContent = 'Waiting for events...\n'
  }
  const es = new EventSource(`/api/job/${jobId}/events`)
  eventSource = es
  es.onmessage = (e) => {
    const d = JSON.parse(e.data)
    const level = d.level || 'info'
    const timestamp = new Date().toLocaleTimeString()
    let text = ''

    if (d.type === 'stats') {
      text = `[${timestamp}] [STATS] ${d.message}`
    } else if (d.type === 'backup') {
      text = `[${timestamp}] [BACKUP] ${d.message}`
    } else if (d.type === 'status') {
      text = `[${timestamp}] [STATUS] ${d.message}`
    } else if (d.type === 'error') {
      text = `[${timestamp}] [ERROR] ${d.message}`
    } else {
      const levelStr = level.toUpperCase()
      text = `[${timestamp}] [${levelStr}] ${d.message}`
    }

    allLogEntries.push({ level, text })

    // Persist logs to job.log in the backend
    fetch(`/api/job/${jobId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ log: allLogEntries }) }).catch(() => { })

    renderLog()
  }
  es.addEventListener('done', () => {
    allLogEntries.push({ level: 'info', text: '[DONE] Job finished' })

    // Final log persistence
    fetch(`/api/job/${jobId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ log: allLogEntries }) }).catch(() => { })

    renderLog()
    eventSource = null
    es.close()

    // Refresh job details to get final status and stats
    fetch(`/api/job/${jobId}`)
      .then(r => r.json())
      .then(j => {
        // Update status badge in detail view
        const statusBadge = document.querySelector('#jobDetail .badge')
        if (statusBadge) {
          statusBadge.className = `badge ${j.status}`
          statusBadge.textContent = j.status
        }

        // Update statistics table
        if (j.stats && Object.keys(j.stats).length > 0) {
          let statsHtml = '<h3>Generated Files</h3><table class="stats-table"><tr><th>File</th><th>Before</th><th>After</th><th>Change</th><th>Diff</th><th>Action</th></tr>'
          for (const [fname, stat] of Object.entries(j.stats)) {
            const deltaClass = stat.delta > 0 ? 'positive' : stat.delta < 0 ? 'negative' : 'neutral'
            const deltaStr = stat.delta >= 0 ? `+${stat.delta}` : `${stat.delta}`

            // Detailed diff info
            let diffHtml = ''
            if (stat.added !== undefined) {
              if (stat.added > 0) diffHtml += `<span class="badge success" style="margin-right:5px">+${stat.added}</span>`
              if (stat.removed > 0) diffHtml += `<span class="badge error">-${stat.removed}</span>`
              if (stat.added === 0 && stat.removed === 0) diffHtml = '<span class="neutral">-</span>'
            } else {
              diffHtml = '<span class="neutral">-</span>'
            }

            // Escape backslashes for HTML onclick attribute (double escape needed)
            const escapedFname = fname.replace(/\\/g, '\\\\')
            statsHtml += `<tr><td>${fname}</td><td>${stat.before}</td><td>${stat.after}</td><td class="${deltaClass}">${deltaStr}</td><td>${diffHtml}</td><td><button onclick="previewFile('${escapedFname}')">Preview</button></td></tr>`
          }
          statsHtml += '</table>'
          if (statsEl) statsEl.innerHTML = statsHtml
        }
      })
      .catch(err => {
        console.error('Failed to refresh job details:', err)
      })

    refreshJobs()
  })
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  refreshJobs()
  refreshServices()
})
