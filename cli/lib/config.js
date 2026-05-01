const fs = require('fs');
const path = require('path');
const os = require('os');
const { input, password } = require('@inquirer/prompts');

const CONFIG_DIR = path.join(os.homedir(), '.config', 'dash');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json');

function getConfig() {
  if (process.env.DASH_URL && process.env.DASH_TOKEN) {
    return { url: process.env.DASH_URL, token: process.env.DASH_TOKEN };
  }
  if (fs.existsSync(CONFIG_FILE)) {
    try {
      const data = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
      return data;
    } catch (e) {
      // Ignore and prompt
    }
  }
  return null;
}

async function promptConfig() {
  console.log('Dashboard configuration missing or invalid. Let\'s set it up.');
  const url = await input({ message: 'Dashboard URL (e.g., dash.example.com):', required: true });
  const token = await password({ message: 'Auth Token:', mask: '*', required: true });
  
  if (!fs.existsSync(CONFIG_DIR)) {
    fs.mkdirSync(CONFIG_DIR, { recursive: true });
  }
  fs.writeFileSync(CONFIG_FILE, JSON.stringify({ url, token }, null, 2), { mode: 0o600 });
  fs.chmodSync(CONFIG_FILE, 0o600);
  console.log('Configuration saved securely.');
  return { url, token };
}

/**
 * Ensures a valid configuration exists, prompting the user if it is missing.
 * @returns {Promise<Object>} Configuration object with {url, token}.
 */
async function ensureConfig() {
  let conf = getConfig();
  if (!conf || !conf.url || !conf.token) {
    conf = await promptConfig();
  }
  return conf;
}

module.exports = { getConfig, promptConfig, ensureConfig };
