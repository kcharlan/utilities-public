#!/usr/bin/env node
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createMacosAppDeployment} from './macos_app_deployment.mjs';
const project='anker_charge_monitor', executable='PrimeMonitor';
const contract=Object.freeze({CFBundleName:'Anker Charge Monitor',CFBundleDisplayName:'Anker Charge Monitor',CFBundleIdentifier:'local.utilities.prime-monitor',CFBundleExecutable:executable,LSMinimumSystemVersion:'27.0',LSUIElement:true,CFBundlePackageType:'APPL'});
const helpers=['tools/deploy_anker_charge_monitor.mjs','tools/deployment_files.mjs','tools/deploy_brew_version.mjs','tools/transaction.mjs','tools/macos_app_deployment.mjs'];
const requiredInputs=['Package.swift','Makefile','Resources/Info.plist','tools/install.sh','tools/resolve_signing_identity.sh'].map(n=>project+'/'+n).concat(helpers);
export const {buildInput,sourceInventory,main}=createMacosAppDeployment({project,executable,contract,helpers,requiredInputs,appName:'Anker Charge Monitor.app',label:'Anker Charge Monitor',envPrefix:'PRIME_MONITOR',receiptName:'.anker-charge-monitor-native.json',backupName:'anker-charge-monitor',removePrefix:'.anker-remove-',receiptPrefix:'.anker-receipt-',buildPrefix:'anker-charge-build-',scriptName:'deploy_anker_charge_monitor.mjs',repoRoot:path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')});

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  main().catch(error=>{console.error('Anker Charge Monitor deployment failed: '+error.message);process.exitCode=1;});
}
