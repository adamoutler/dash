const { getConfig } = require('./config');

async function fetchDash(endpoint, options = {}) {
  const config = getConfig();
  if (!config) throw new Error('Missing config');
  
  let url = config.url.replace(/\/+$/, '');
  if (!endpoint.startsWith('/')) endpoint = '/' + endpoint;
  
  const headers = {
    'Authorization': `Bearer ${config.token}`,
    'Content-Type': 'application/json',
    ...(options.headers || {})
  };
  
  try {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), 5000);
    
    const response = await fetch(`${url}${endpoint}`, {
      ...options,
      headers,
      signal: controller.signal
    });
    clearTimeout(id);
    
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        throw new Error('Authentication failed (401/403). Try running "dash login".');
      }
      let errStr = `HTTP ${response.status} ${response.statusText}`;
      try {
        const errObj = await response.json();
        if (errObj.detail) errStr += `: ${errObj.detail}`;
      } catch (e) {}
      throw new Error(errStr);
    }
    
    return await response.json();
  } catch (error) {
    if (error.name === 'AbortError' || error.name === 'TypeError') {
      throw new Error(`Cannot connect to dashboard at ${config.url}. Please check your connection.`);
    }
    throw error;
  }
}

module.exports = { fetchDash };
