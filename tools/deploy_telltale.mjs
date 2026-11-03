#!/usr/bin/env node
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createMacosAppDeployment} from './macos_app_deployment.mjs';
const project='telltale', executable='Telltale';
export const contract=Object.freeze({CFBundleName:'Telltale',CFBundleDisplayName:'Telltale',CFBundleIdentifier:'local.utilities.telltale',CFBundleExecutable:executable,LSMinimumSystemVersion:'27.0',LSUIElement:true,CFBundlePackageType:'APPL'});
const helpers=['tools/check_no_temp_leaks.sh','tools/deploy_telltale.mjs','tools/deployment_files.mjs','tools/deploy_brew_version.mjs','tools/transaction.mjs','tools/macos_app_deployment.mjs'];
export const requiredInputs=Object.freeze(['Package.swift','Makefile','Resources/Info.plist','Resources/Fonts/BarlowSemiCondensed-Medium.ttf','Resources/Fonts/BarlowSemiCondensed-Regular.ttf','Resources/Fonts/OFL.txt','tools/install.sh','tools/resolve_signing_identity.sh'].map(n=>project+'/'+n).concat(helpers));
export const {buildInput,sourceInventory,main}=createMacosAppDeployment({project,executable,contract,helpers,requiredInputs,appName:'Telltale.app',label:'Telltale',envPrefix:'TELLTALE',receiptName:'.telltale-native.json',backupName:'telltale',removePrefix:'.telltale-remove-',receiptPrefix:'.telltale-receipt-',buildPrefix:'telltale-build-',scriptName:'deploy_telltale.mjs',repoRoot:path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')});

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  main().catch(error=>{console.error('Telltale deployment failed: '+error.message);process.exitCode=1;});
}
