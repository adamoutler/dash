const { fetchDash } = require('../api');
const { formatError, formatSuccess, formatPending, formatInfo } = require('../ui');
const { execSync } = require('child_process');

function isRecentCommit() {
  try {
    const stdout = execSync('git log -1 --format=%ct', { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'] });
    const commitTime = parseInt(stdout.trim(), 10);
    const currentTime = Math.floor(Date.now() / 1000);
    return (currentTime - commitTime) <= 20;
  } catch (err) {
    return false;
  }
}

/**
 * Polls the dashboard API until the specified repository's pipeline finishes.
 * @param {string} repo - Repository name or owner/name to wait for.
 */
module.exports = async function(repo) {
  try {
    if (!repo) {
      console.error(formatError('Repository argument is required for wait command'));
      process.exit(1);
    }
    
    console.log(formatPending(`Waiting for pipeline on ${repo} to complete...`));
    
    let transientFailures = 0;
    const MAX_TRANSIENT_FAILURES = 5;
    let attempts_when_not_running = 0;
    let was_running = false;
    
    // Poll every 5 seconds
    while (true) {
      let data;
      try {
        data = await fetchDash(`/api/status?repo=${encodeURIComponent(repo)}`);
        transientFailures = 0;
      } catch (err) {
        transientFailures++;
        console.error(formatError(`Transient error (${transientFailures}/${MAX_TRANSIENT_FAILURES}): ${err.message}`));
        if (transientFailures >= MAX_TRANSIENT_FAILURES) {
          process.exit(1);
        }
        await new Promise(r => setTimeout(r, 5000));
        continue;
      }
      
      const item = Array.isArray(data) ? data[0] : data;
      if (!item) {
        console.error(formatError('No pipeline found for repository'));
        process.exit(1);
      }
      
      const status = item.status || 'unknown';
      const isRunning = ['running', 'in_progress', 'queued', 'waiting', 'requested', 'pending'].includes(status);
      
      if (isRunning) {
        was_running = true;
        await new Promise(r => setTimeout(r, 5000));
        continue;
      }
      
      if (item.status === 'success' || item.status === 'passed') {
        console.log(formatSuccess(`Pipeline succeeded!`));
        if (item.url) console.log(`  Link: ${item.url}`);
        process.exit(0);
      } else if (item.status === 'failed' || item.status === 'error') {
        console.error(formatError(`Pipeline failed!`));
        if (item.url) console.log(`  Link: ${item.url}`);
        process.exit(1);
      }
      
      // Not running, not finished (could be no job in progress yet)
      if (!was_running) {
        if (isRecentCommit() && attempts_when_not_running < 12) { // Wait up to 60s
          attempts_when_not_running++;
          await new Promise(r => setTimeout(r, 5000));
          continue;
        } else {
           console.log(formatInfo('No pipeline in progress.'));
           process.exit(0);
        }
      }
      
      // Still running somehow? Wait and retry
      await new Promise(r => setTimeout(r, 5000));
    }
  } catch (err) {
    console.error(formatError(err.message));
    process.exit(1);
  }
};
