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

async function refreshJobs(){
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
        let statsHtml = '<h3>Generated Files</h3><table class="stats-table"><tr><th>File</th><th>Before</th><th>After</th><th>Change</th><th>Action</th></tr>'
        for (const [fname, stat] of Object.entries(j.stats)) {
          const deltaClass = stat.delta > 0 ? 'positive' : stat.delta < 0 ? 'negative' : 'neutral'
          const deltaStr = stat.delta >= 0 ? `+${stat.delta}` : `${stat.delta}`
          statsHtml += `<tr><td>${fname}</td><td>${stat.before}</td><td>${stat.after}</td><td class="${deltaClass}">${deltaStr}</td><td><button onclick="previewFile('${fname}')">Preview</button></td></tr>`
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

async function previewFile(filename) {
  try {
    const res = await fetch(`/api/file/preview?path=openhab/${filename}`)
    if (!res.ok) throw new Error('Failed to load file')
    const data = await res.json()
    
    const dialog = document.getElementById('filePreviewDialog')
    document.getElementById('previewFileName').textContent = filename
    document.getElementById('previewContent').textContent = data.content
    dialog.showModal()
  } catch (e) {
    alert('Error loading file: ' + e.message)
  }
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

uploadForm.addEventListener('submit', async (e)=>{
  e.preventDefault()
  const f = fileInput.files[0]
  if(!f) return alert('select a file')
  const fd = new FormData()
  fd.append('file', f)
  const pwd = passwordInput.value
  if (pwd) {
    fd.append('password', pwd)
  }
  statusEl.textContent = 'Uploading...'
  try {
    const res = await fetch('/api/upload', {method:'POST', body: fd})
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

function startEvents(jobId){
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
  es.onmessage = (e)=>{
    const d = JSON.parse(e.data)
    const level = d.level || 'info'
    const timestamp = new Date().toLocaleTimeString()
    let text = ''
    
    if(d.type === 'stats'){
      text = `[${timestamp}] [STATS] ${d.message}`
    } else if(d.type === 'backup'){
      text = `[${timestamp}] [BACKUP] ${d.message}`
    } else if(d.type === 'status'){
      text = `[${timestamp}] [STATUS] ${d.message}`
    } else if(d.type === 'error'){
      text = `[${timestamp}] [ERROR] ${d.message}`
    } else {
      const levelStr = level.toUpperCase()
      text = `[${timestamp}] [${levelStr}] ${d.message}`
    }
    
    allLogEntries.push({ level, text })
    
    // Persist logs to job.log in the backend
    fetch(`/api/job/${jobId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ log: allLogEntries }) }).catch(() => {})
    
    renderLog()
  }
  es.addEventListener('done', ()=>{ 
    allLogEntries.push({ level: 'info', text: '[DONE] Job finished' })
    
    // Final log persistence
    fetch(`/api/job/${jobId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ log: allLogEntries }) }).catch(() => {})
    
    renderLog()
    eventSource = null
    es.close()
    refreshJobs()
  })
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  refreshJobs()
  refreshServices()
})
