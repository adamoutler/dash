const { promptConfig } = require('../config');
const { formatSuccess } = require('../ui');

module.exports = async function() {
  await promptConfig();
  console.log(formatSuccess('Successfully logged in and configured!'));
};
