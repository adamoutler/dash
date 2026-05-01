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
  /**
   * Formats an error message with a red prefix and error icon.
   * @param {string} msg - The error message.
   * @returns {string} Formatted error string.
   */
  formatError: (msg) => `${module.exports.icons.error} ${pc.red('Error:')} ${msg}`,
  /**
   * Formats a success message with a green color and success icon.
   * @param {string} msg - The success message.
   * @returns {string} Formatted success string.
   */
  formatSuccess: (msg) => `${module.exports.icons.success} ${pc.green(msg)}`,
  /**
   * Formats an informational message with a cyan color and info icon.
   * @param {string} msg - The info message.
   * @returns {string} Formatted info string.
   */
  formatInfo: (msg) => `${module.exports.icons.info} ${pc.cyan(msg)}`,
  /**
   * Formats a pending message with a yellow color and pending icon.
   * @param {string} msg - The pending message.
   * @returns {string} Formatted pending string.
   */
  formatPending: (msg) => `${module.exports.icons.running} ${pc.yellow(msg)}`,
};
