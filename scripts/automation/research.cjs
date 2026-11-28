'use strict';

// Controller-owned, bounded public evidence collection. Model permissions stay read-only.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const SOURCE_LIMIT = 256000;
const TOTAL_LIMIT = 768000;
const MAX_SOURCES = 12;
const REVISION = /^(?:[a-f0-9]{40}|v?\d+\.\d+\.\d+)$/;
const hash = value => crypto.createHash('sha256').update(value).digest('hex');

function sourceRequests(text, repo) {
  const requests = new Map();
  for (const match of text.matchAll(/https:\/\/[^\s<>\])]+/g)) {
    let url;
    try { url = new URL(match[0]); } catch { continue; }
    if (url.username || url.password || url.port || url.search) continue;
    const parts = url.pathname.split('/').filter(Boolean);
    if (url.hostname === 'github.com') {
      if (!parts.every(part => /^[A-Za-z0-9_.-]+$/.test(part) && part !== '.' && part !== '..')) continue;
      if (parts[2] === 'blob' && parts.length > 4 && REVISION.test(parts[3])) {
        url.hash = '';
        requests.set(url.href, {url: url.href, kind: 'file', owner: parts[0], repo: parts[1],
          ref: parts[3], path: parts.slice(4).join('/')});
      } else if (parts[2] === 'commit' && parts.length === 4 && /^[a-f0-9]{40}$/.test(parts[3]) &&
          parts[0] === repo.owner && parts[1] === repo.repo) {
        url.hash = '';
        requests.set(url.href, {url: url.href, kind: 'commit', ref: parts[3], ...repo});
      }
    } else if (/^(?:www|v\d+)\.openhab\.org$/.test(url.hostname) &&
        /^\/addons\/[A-Za-z0-9/_-]+\/?$/.test(url.pathname)) {
      url.hash = '';
      requests.set(url.href, {url: url.href, kind: 'documentation'});
    }
  }
  return [...requests.values()];
}

async function documentation(url, fetchDocument) {
  // No token, cookies, arbitrary hosts, query strings or redirects.
  const response = await fetchDocument(url, {redirect: 'manual', signal: AbortSignal.timeout(15000)});
  if (!response.ok || !/text\/(?:html|plain)/i.test(response.headers.get('content-type') || ''))
    throw new Error('unavailable');
  const chunks = [];
  let size = 0;
  for await (const chunk of response.body) {
    size += chunk.length;
    if (size > SOURCE_LIMIT) throw new Error('too_large');
    chunks.push(chunk);
  }
  // Store the whole response, including its version context; never silently clip it.
  return Buffer.concat(chunks).toString('utf8');
}

async function collectEvidence({github, repo, text, evidenceDirectory, fetchDocument = fetch}) {
  const requests = sourceRequests(text, repo);
  const result = {sources: [], omitted_sources: Math.max(0, requests.length - MAX_SOURCES),
    total_bytes: 0, policy: 'Pinned GitHub files, same-repository commits, official openHAB documentation'};
  if (evidenceDirectory) fs.mkdirSync(evidenceDirectory, {recursive: true});
  for (const source of requests.slice(0, MAX_SOURCES)) {
    const record = {url: source.url, kind: source.kind, status: 'unavailable'};
    try {
      let content;
      if (source.kind === 'commit') {
        const {data} = await github.rest.repos.getCommit({...repo, ref: source.ref, per_page: 100});
        if (data.sha !== source.ref) throw new Error('unavailable');
        record.revision = data.sha;
        record.incomplete = !Array.isArray(data.files) || data.files.some(file => !file.patch) || data.files.length >= 100;
        content = JSON.stringify({sha: data.sha, message: data.commit.message, files: data.files});
      } else if (source.kind === 'file') {
        const target = {owner: source.owner, repo: source.repo};
        const {data: commit} = await github.rest.repos.getCommit({...target, ref: source.ref});
        if (!/^[a-f0-9]{40}$/.test(commit.sha)) throw new Error('unavailable');
        record.revision = commit.sha;
        const {data} = await github.rest.repos.getContent({...target, path: source.path, ref: commit.sha});
        if (data.encoding !== 'base64' || typeof data.content !== 'string') throw new Error('unavailable');
        content = Buffer.from(data.content, 'base64').toString('utf8');
      } else {
        content = await documentation(source.url, fetchDocument);
        record.version_pinned = false;
      }
      const bytes = Buffer.byteLength(content);
      if (bytes > SOURCE_LIMIT || result.total_bytes + bytes > TOTAL_LIMIT) {
        record.status = 'size_limit';
      } else if (!evidenceDirectory) {
        record.status = 'not_materialized';
      } else {
        record.sha256 = hash(content);
        record.file = '.planner-evidence/' + hash(source.url) + '.txt';
        fs.writeFileSync(path.join(evidenceDirectory, path.basename(record.file)),
          `UNTRUSTED REFERENCE DATA\nURL: ${source.url}\nRevision: ${record.revision || 'unversioned'}\n\n${content}`,
          {encoding: 'utf8', flag: 'wx'});
        record.status = 'available';
        result.total_bytes += bytes;
      }
    } catch {
      record.status = 'unavailable';
    }
    result.sources.push(record);
  }
  return result;
}

module.exports = {collectEvidence, sourceRequests};
