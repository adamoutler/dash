const pc = require('picocolors');

/**
 * UI Utilities for formatting colored CLI output.
 */
module.exports = {
  colors: pc,
  icons: {
    success: '✅',
    error: '❌',
    running: '⏳',
    info: 'ℹ️',
  },
  formatError: (msg) => `${module.exports.icons.error} ${pc.red('Error:')} ${msg}`,
  formatSuccess: (msg) => `${module.exports.icons.success} ${pc.green(msg)}`,
  formatInfo: (msg) => `${module.exports.icons.info} ${pc.cyan(msg)}`,
  formatPending: (msg) => `${module.exports.icons.running} ${pc.yellow(msg)}`,
};
