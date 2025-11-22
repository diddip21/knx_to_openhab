const uploadForm = document.getElementById('uploadForm')
const fileInput = document.getElementById('fileInput')
const jobsList = document.getElementById('jobs')
const logEl = document.getElementById('log')
const statusEl = document.getElementById('status')
const jobDetailEl = document.getElementById('jobDetail')
const logSectionEl = document.getElementById('log-section')
const detailSectionEl = document.getElementById('detail-section')
const rollbackDialog = document.getElementById('rollbackDialog')
const backupSelect = document.getElementById('backupSelect')
const rollbackStatusEl = document.getElementById('rollbackStatus')

let currentJobId = null

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
    `
    jobsList.appendChild(li)
  })
}

function showJobDetail(jobId) {
  currentJobId = jobId
  detailSectionEl.style.display = 'block'
  logSectionEl.style.display = 'block'
  
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
      logEl.textContent = j.log.join('\n') || '(no logs yet)'
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
  const serviceStatusEl = document.getElementById('serviceStatus')
  serviceStatusEl.textContent = 'Restarting ' + service + '...'
  try {
    const res = await fetch('/api/service/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service })
    })
    const data = await res.json()
    if (data.ok) {
      serviceStatusEl.textContent = '✓ ' + service + ' restarted'
    } else {
      serviceStatusEl.textContent = '✗ Error: ' + data.output
    }
  } catch (e) {
    serviceStatusEl.textContent = '✗ Error: ' + e.message
  }
  btn.disabled = false
}

uploadForm.addEventListener('submit', async (e)=>{
  e.preventDefault()
  const f = fileInput.files[0]
  if(!f) return alert('select a file')
  const fd = new FormData()
  fd.append('file', f)
  statusEl.textContent = 'Uploading...'
  try {
    const res = await fetch('/api/upload', {method:'POST', body: fd})
    if (!res.ok) throw new Error('Upload failed: ' + res.status)
    const job = await res.json()
    statusEl.textContent = `Job started: ${job.id}`
    refreshJobs()
    showJobDetail(job.id)
    startEvents(job.id)
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`
  }
})

function startEvents(jobId){
  logEl.textContent = 'Waiting for events...\n'
  const es = new EventSource(`/api/job/${jobId}/events`)
  es.onmessage = (e)=>{
    const d = JSON.parse(e.data)
    if(d.type === 'log'){
      logEl.textContent += d.message + '\n'
    } else if(d.type === 'info'){
      logEl.textContent += '[INFO] ' + d.message + '\n'
    } else if(d.type === 'status'){
      logEl.textContent += '[STATUS] ' + d.message + '\n'
    } else if(d.type === 'backup'){
      logEl.textContent += '[BACKUP] ' + d.message + '\n'
    } else if(d.type === 'error'){
      logEl.textContent += '[ERROR] ' + d.message + '\n'
    }
    logEl.scrollTop = logEl.scrollHeight
  }
  es.addEventListener('done', ()=>{ 
    logEl.textContent += '\n[DONE] Job finished\n'
    es.close()
    refreshJobs()
  })
}

// Initial refresh
refreshJobs()
// Auto-refresh jobs every 5 seconds
setInterval(refreshJobs, 5000)
