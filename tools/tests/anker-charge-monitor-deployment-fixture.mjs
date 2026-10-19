// Invented read-only fleet artifacts. No application execution or signing.
import fs from 'node:fs';
import path from 'node:path';
import {sourceInventory} from '../deploy_anker_charge_monitor.mjs';
import {appTreeHash} from '../deploy_brew_version.mjs';
const [repo,home]=process.argv.slice(2);
const app=path.join(home,'Applications/Anker Charge Monitor.app'),scripts=path.join(home,'Library/Scripts');
fs.mkdirSync(path.join(app,'Contents/MacOS'),{recursive:true});
fs.writeFileSync(path.join(app,'Contents/MacOS/PrimeMonitor'),'synthetic never-executed app\n',{mode:0o755});
fs.copyFileSync(path.join(repo,'anker_charge_monitor/Resources/Info.plist'),path.join(app,'Contents/Info.plist'));
fs.chmodSync(path.join(app,'Contents/Info.plist'),0o644);
fs.writeFileSync(path.join(scripts,'.anker-charge-monitor-native.json'),JSON.stringify({schema:1,sourceHash:sourceInventory(repo).sourceHash,version:'0.2.0',appTreeHash:appTreeHash(app),signingIdentity:'A'.repeat(40)})+'\n',{mode:0o600});
