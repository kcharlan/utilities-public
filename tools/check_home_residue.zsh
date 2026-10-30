#!/bin/zsh
# Report only direct-child names and ages; do not traverse or modify entries.
set -eu
export LC_ALL=C
if [[ ! -d ${HOME:-} || ! -r $HOME || ! -x $HOME ]]; then
  print -u2 'check_home_residue: cannot read HOME'
  exit 2
fi
now=$(date +%s)
count=0
for entry in "$HOME"/.*(DN); do
  name=${entry:t}
  if [[ $name =~ '^\..+\.[A-Za-z0-9]{6}$' && ${name##*.} != backup ]] ||
     [[ $name =~ '^\..+-[A-Za-z0-9]{8}$' && ${name##*-} =~ '[A-Z0-9]' ]]; then
    if ! modified=$(stat -f '%m' -- "$entry"); then
      print -u2 'check_home_residue: could not read an entry timestamp'
      exit 2
    fi
    age=$((now - modified))
    if (( age > 86400 )); then
      print -r -- "$name: $((age / 86400)) days old"
      (( count += 1 ))
    fi
  fi
done
if (( count )); then
  print -r -- "check_home_residue: $count candidate(s)"
  exit 1
fi
print 'check_home_residue: OK'
