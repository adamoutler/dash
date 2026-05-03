const { fetchDash } = require('../api');
const { formatError, formatSuccess, formatPending, formatInfo } = require('../ui');
const { execFileSync } = require('child_process');

const MAX_TRANSIENT_FAILURES = 5;
const WAIT_INTERVAL_MS = 5000;
const MAX_ATTEMPTS_WHEN_NOT_RUNNING = 12;

function isRecentCommit() {
  try {
    const stdout = execFileSync('git', ['log', '-1', '--format=%ct'], { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
    const commitTime = parseInt(stdout.trim(), 10);
    const currentTime = Math.floor(Date.now() / 1000);
    return (currentTime - commitTime) <= 20;
  } catch (err) {
    return false;
  }}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function fetchStatusWithRetry(repo, state) {
  try {
    const data = await fetchDash(`/api/status?repo=${encodeURIComponent(repo)}`);
    state.transientFailures = 0;
    return Array.isArray(data) ? data[0] : data;
  } catch (err) {
    state.transientFailures++;
    console.error(formatError(`Transient error (${state.transientFailures}/${MAX_TRANSIENT_FAILURES}): ${err.message}`));
    if (state.transientFailures >= MAX_TRANSIENT_FAILURES) {
      process.exit(1);
    }
    return null; // Return null to indicate failure but keep waiting if under max
  }
}

function evaluatePipeline(item, state) {
  const status = item.status || 'unknown';
  
  if (['success', 'passed'].includes(status)) {
    console.log(formatSuccess(`Pipeline succeeded!`));
    if (item.url) console.log(`  Link: ${item.url}`);
    return { wait: false, code: 0 };
  }
  
  if (['failed', 'error', 'cancelled', 'action_required', 'timed_out'].includes(status)) {
    console.error(formatError(`Pipeline stopped with status: ${status}`));
    if (item.url) console.log(`  Link: ${item.url}`);
    return { wait: false, code: 1 };
  }
  
  const isRunning = ['running', 'in_progress', 'queued', 'waiting', 'requested', 'pending'].includes(status);
  
  if (isRunning) {
    state.wasRunning = true;
    return { wait: true }; // continue waiting
  }
  
  if (!state.wasRunning) {
    if (isRecentCommit() && state.attemptsWhenNotRunning < MAX_ATTEMPTS_WHEN_NOT_RUNNING) {
      state.attemptsWhenNotRunning++;
      return { wait: true }; // continue waiting
    }
    console.log(formatInfo('No pipeline in progress.'));
    return { wait: false, code: 0 };
  }
  
  return { wait: true }; // Wait and retry
}

/**
 * Polls the dashboard API until the specified repository's pipeline finishes.
 * @param {string} repo - Repository name or owner/name to wait for.
 */
module.exports = async function(repo) {
  if (!repo) {
    console.error(formatError('Repository argument is required for wait command'));
    process.exit(1);
  }
  
  console.log(formatPending(`Waiting for pipeline on ${repo} to complete...`));
  
  const state = {
    transientFailures: 0,
    attemptsWhenNotRunning: 0,
    wasRunning: false
  };
  
  while (true) {
    const item = await fetchStatusWithRetry(repo, state);
    
    // If item is returned, evaluate it. If null, it was a transient error, continue waiting.
    if (item === undefined) { // No pipeline found from API
      console.error(formatError('No pipeline found for repository'));
      process.exit(1);
    } else if (item) {
      const result = evaluatePipeline(item, state);
      if (!result.wait) {
        if (result.code !== undefined) {
          process.exit(result.code);
        }
        break;
      }
    }
    
    await sleep(WAIT_INTERVAL_MS);
  }
};
