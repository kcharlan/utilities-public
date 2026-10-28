// Port: tools/tests/anker-charge-monitor-deployment-fixture.mjs, whole module, be26b1b.
// Adaptation: Telltale's app, executable and receipt; the version comes from the fixture
// repository's Info.plist instead of a literal.
// Invented read-only fleet artifacts. No application execution or signing. Everything is
// written inside the caller's fixture home, which the caller removes.
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {sourceInventory} from '../deploy_telltale.mjs';
import {appTreeHash} from '../deploy_brew_version.mjs';
const [repo,home]=process.argv.slice(2);
const plist=path.join(repo,'telltale/Resources/Info.plist');
const app=path.join(home,'Applications/Telltale.app'),scripts=path.join(home,'Library/Scripts');
fs.mkdirSync(path.join(app,'Contents/MacOS'),{recursive:true});
fs.writeFileSync(path.join(app,'Contents/MacOS/Telltale'),'synthetic never-executed app\n',{mode:0o755});
fs.copyFileSync(plist,path.join(app,'Contents/Info.plist'));
fs.chmodSync(path.join(app,'Contents/Info.plist'),0o644);
const version=execFileSync('/usr/bin/plutil',['-extract','CFBundleShortVersionString','raw','-o','-','--',plist],{encoding:'utf8'}).trim();
fs.writeFileSync(path.join(scripts,'.telltale-native.json'),JSON.stringify({schema:1,sourceHash:sourceInventory(repo).sourceHash,version,appTreeHash:appTreeHash(app),signingIdentity:'A'.repeat(40)})+'\n',{mode:0o600});
