const { promptConfig } = require('../config');
const { formatSuccess } = require('../ui');

/**
 * Manually triggers the interactive setup to update credentials.
 */
module.exports = async function loginCommand() {
  await promptConfig();
  console.log(formatSuccess('Successfully logged in and configured!'));
};
