const fs = require('fs');
const fsPromises = require('fs').promises;
const path = require('path');
const os = require('os');
const { input, password } = require('@inquirer/prompts');

const CONFIG_DIR = path.join(os.homedir(), '.config', 'dash');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json');

async function getConfig() {
  if (process.env.DASH_URL && process.env.DASH_TOKEN) {
    return { url: process.env.DASH_URL, token: process.env.DASH_TOKEN };
  }
  try {
    await fsPromises.access(CONFIG_FILE);
    const fileContent = await fsPromises.readFile(CONFIG_FILE, 'utf8');
    const data = JSON.parse(fileContent);
    return data;
  } catch (e) {
    console.error(`Invalid or unreadable config at ${CONFIG_FILE}. Prompting for new config.`);
  }
  return null;
}

async function promptConfig() {
  console.log('Dashboard configuration missing or invalid. Let\'s set it up.');
  const url = await input({ message: 'Dashboard URL (e.g., dash.example.com):', required: true });
  const token = await password({ message: 'Auth Token:', mask: '*', required: true });
  
  try {
    await fsPromises.access(CONFIG_DIR);
  } catch {
    await fsPromises.mkdir(CONFIG_DIR, { recursive: true });
  }
  await fsPromises.writeFile(CONFIG_FILE, JSON.stringify({ url, token }, null, 2), { mode: 0o600 });
  await fsPromises.chmod(CONFIG_FILE, 0o600);
  console.log('Configuration saved securely.');
  return { url, token };
}

/**
 * Ensures a valid configuration exists, prompting the user if it is missing.
 * @returns {Promise<Object>} Configuration object with {url, token}.
 */
async function ensureConfig() {
  let conf = await getConfig();
  if (!conf || !conf.url || !conf.token) {
    conf = await promptConfig();
  }
  return conf;
}

module.exports = { getConfig, promptConfig, ensureConfig };
