#!/usr/bin/env node
// Direct-copy installer for the standalone drawdown calculator page.
import {runCalculatorPageDeployment} from './calculator_page_deployment.mjs';

runCalculatorPageDeployment({
  filename: 'drawdown.html', label: 'Drawdown', backupName: 'drawdown',
  script: 'deploy_drawdown.mjs',
});
