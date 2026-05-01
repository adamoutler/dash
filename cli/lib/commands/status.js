const { fetchDash } = require('../api');
const { formatError, formatSuccess, formatPending, formatInfo } = require('../ui');

module.exports = async function(repo) {
  try {
    let url = '/api/status';
    if (repo) url += `?repo=${encodeURIComponent(repo)}`;
    
    const data = await fetchDash(url);
    
    if (!data || (Array.isArray(data) && data.length === 0)) {
      console.log(formatInfo('No status available'));
      return;
    }
    
    if (Array.isArray(data)) {
      const items = data.filter(Boolean);
      if (items.length === 0) {
        console.log(formatInfo('No status available'));
        return;
      }
      items.forEach(renderStatus);
    } else {
      renderStatus(data);
    }
  } catch (err) {
    console.error(formatError(err.message));
    process.exit(1);
  }
};

/**
 * Helper to render the status of a single pipeline item.
 * @param {Object} item - Pipeline status data.
 */
function renderStatus(item) {
  let statusStr = '';
  if (item.status === 'success' || item.status === 'passed') statusStr = formatSuccess(item.status);
  else if (item.status === 'failed' || item.status === 'error') statusStr = formatError(item.status);
  else statusStr = formatPending(item.status);
  
  console.log(`\n${formatInfo(item.repo || item.name)}`);
  console.log(`  Status: ${statusStr}`);
  if (item.url) console.log(`  Link:   ${item.url}`);
}
