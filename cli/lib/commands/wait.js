const { fetchDash } = require('../api');
const { formatError, formatSuccess, formatPending, formatInfo } = require('../ui');

module.exports = async function(repo) {
  try {
    if (!repo) {
      console.error(formatError('Repository argument is required for wait command'));
      process.exit(1);
    }
    
    console.log(formatPending(`Waiting for pipeline on ${repo} to complete...`));
    
    let transientFailures = 0;
    const MAX_TRANSIENT_FAILURES = 5;
    
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
      
      if (item.status === 'success' || item.status === 'passed') {
        console.log(formatSuccess(`Pipeline succeeded!`));
        if (item.url) console.log(`  Link: ${item.url}`);
        process.exit(0);
      } else if (item.status === 'failed' || item.status === 'error') {
        console.error(formatError(`Pipeline failed!`));
        if (item.url) console.log(`  Link: ${item.url}`);
        process.exit(1);
      }
      
      // Still running, sleep and retry
      await new Promise(r => setTimeout(r, 5000));
    }
  } catch (err) {
    console.error(formatError(err.message));
    process.exit(1);
  }
};
