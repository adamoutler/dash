#!/usr/bin/env node

/**
 * Main entrypoint for the dash CLI.
 */
const { program } = require('commander');
const { version } = require('../../package.json');
const statusCmd = require('../lib/commands/status');
const waitCmd = require('../lib/commands/wait');
const loginCmd = require('../lib/commands/login');
const { ensureConfig } = require('../lib/config');

program
  .name('dash')
  .description('Interact with your CI/CD monitoring hub from the terminal')
  .version(version);

// Intercept to check config first
program.hook('preAction', async (thisCommand, actionCommand) => {
  if (actionCommand.name() !== 'login') {
    await ensureConfig();
  }
});

program
  .command('status')
  .description('View current status of a repository\'s pipelines')
  .argument('[repo]', 'Repository name or owner/name')
  .action(statusCmd);

program
  .command('wait')
  .description('Block and poll until the current running pipeline completes')
  .argument('[repo]', 'Repository name or owner/name')
  .action(waitCmd);

program
  .command('login')
  .description('Manually trigger the interactive setup to update credentials')
  .action(loginCmd);

program.parseAsync(process.argv).catch(err => {
  console.error(err);
  process.exit(1);
});
