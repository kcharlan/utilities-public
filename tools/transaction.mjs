// Installers register recovery before changing destinations and builders register
// cleanup as soon as they own scratch. Signal handling waits for synchronous
// subprocesses to return before cleaning or restoring anything they may use.
export async function runTransaction({name, admit, isCurrent, build, install, verify, recovery}) {
  let interrupted;
  const onInt=()=>{interrupted ||= 'SIGINT';}, onTerm=()=>{interrupted ||= 'SIGTERM';};
  process.on('SIGINT',onInt); process.on('SIGTERM',onTerm);
  const checkpoint=async()=>{
    await new Promise(resolve=>setImmediate(resolve));
    if(interrupted) throw new Error(name+' interrupted by '+interrupted);
  };
  let cleanup, restore, result, primary;
  try {
    if(recovery) {result=recovery(); await checkpoint(); return result;}
    admit(); await checkpoint();
    if(isCurrent()) return;
    const built=build(fn=>{cleanup=fn;});
    if(built?.cleanup)cleanup=built.cleanup;
    await checkpoint();
    result=install(built?.value,fn=>{restore=fn;});
    if(typeof result==='function')restore=result;
    await checkpoint();
    verify(built?.value); await checkpoint();
  } catch(error) {primary=error;}
  finally {
    try {cleanup?.();} catch(error) {
      primary=primary?new AggregateError([primary,error],`${name}: ${primary.message}; cleanup failed: ${error.message}`):error;
    }
    if(primary&&restore) {
      try {restore();} catch(error) {
        primary=new AggregateError([primary,error],`${name}: ${primary.message}; restoration failed: ${error.message}`);
      }
    }
    process.removeListener('SIGINT',onInt); process.removeListener('SIGTERM',onTerm);
  }
  if(primary)throw primary;
  return result;
}
