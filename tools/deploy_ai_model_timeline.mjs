#!/usr/bin/env node
// Direct-copy installer for the standalone AI model timeline page.
import {runCalculatorPageDeployment} from './calculator_page_deployment.mjs';

runCalculatorPageDeployment({
  filename: 'ai-model-timeline.html', label: 'Timeline', backupName: 'ai-model-timeline',
  script: 'deploy_ai_model_timeline.mjs',
});
