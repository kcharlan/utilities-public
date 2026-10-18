// Invented artifacts for the read-only fleet audit; lifecycle tests compile C.
import fs from 'node:fs';
import path from 'node:path';
import {sourceInventory, appTreeHash} from '../deploy_brew_version.mjs';
import {sha} from '../deployment_files.mjs';
const [repo,home]=process.argv.slice(2);
const scripts=path.join(home,'Library/Scripts'),app=path.join(home,'Applications/Brew Version.app');
fs.mkdirSync(path.join(app,'Contents/MacOS'),{recursive:true});
fs.writeFileSync(path.join(app,'Contents/MacOS/BrewVersion'),'synthetic app artifact\n',{mode:0o755});
fs.writeFileSync(path.join(app,'Contents/Info.plist'),fs.readFileSync(path.join(repo,'brew_version/Resources/Info.plist')));
const bytes=Buffer.from('synthetic native command for read-only audit\n');
fs.writeFileSync(path.join(scripts,'brew-version'),bytes,{mode:0o755});fs.chmodSync(path.join(scripts,'brew-version'),0o755);
const version=/<key>CFBundleShortVersionString<\/key>\s*<string>([^<]+)<\/string>/.exec(fs.readFileSync(path.join(repo,'brew_version/Resources/Info.plist'),'utf8'))[1];
fs.writeFileSync(path.join(scripts,'.brew-version-native.json'),JSON.stringify({schema:1,sourceHash:sourceInventory(repo).sourceHash,version,commandHash:sha(bytes),commandMode:0o755,appTreeHash:appTreeHash(app)}),{mode:0o600});
