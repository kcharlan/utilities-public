// Invented receipt/binary for read-only fleet fixtures; lifecycle tests compile C.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {sourceInventory} from '../deploy_colophon_native.mjs';
const [repo, home] = process.argv.slice(2);
const sourceHash = sourceInventory(repo).sourceHash;
const scripts = path.join(home, 'Library/Scripts');
const bytes = Buffer.from('synthetic native artifact for read-only audit\n');
fs.writeFileSync(path.join(scripts, 'colophon'), bytes, {mode: 0o755});
fs.chmodSync(path.join(scripts, 'colophon'), 0o755);
fs.writeFileSync(path.join(scripts, '.colophon-native.json'), JSON.stringify({
  schema: 1, sourceHash, binaryHash: crypto.createHash('sha256').update(bytes).digest('hex'), mode: 0o755
}), {mode: 0o600});
