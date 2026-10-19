#!/bin/bash
set -eu
scanner="$(cd "$(dirname "$0")/../.." && pwd)/tools/check_secrets.sh"
work=$(mktemp -d)
work=$(cd "$work" && pwd -P)
trap 'chmod -R u+rwX "$work"; rm -rf "$work"' EXIT
chmod 700 "$work"
cd "$work"
git init -q
printf '.secrets-patterns\nignored/\n' > .gitignore
printf 'owner@example.invalid\nserial[.*]fixture\nuser-fixture\ncertificate-fixture\ntoken-fixture\n' > .secrets-patterns
chmod 600 .secrets-patterns
cp .secrets-patterns patterns-copy
mv patterns-copy "$work/../$(basename "$work").patterns"
patterns="$work/../$(basename "$work").patterns"
trap 'chmod -R u+rwX "$work"; rm -rf "$work"; rm -f "$patterns"' EXIT
check() {
  local want=$1 code=0
  ANKER_CHARGE_MONITOR_SECRETS_FILE="$work/.secrets-patterns" bash "$scanner" > result 2>&1 || code=$?
  if [ "$code" != "$want" ]; then echo "FAIL: expected $want, got $code"; exit 1; fi
  if grep -F -f "$patterns" result >/dev/null 2>&1; then echo 'FAIL: identifier disclosed'; exit 1; fi
  if [ "$want" = 0 ] && [ "$(cat result)" != clean ]; then echo 'FAIL: clean contract'; exit 1; fi
  rm result
}
printf 'device_sn auth_token BEGIN PRIVATE KEY\n' > protocol
printf 'ff09460103010f0a00\n' > fixture
git add .gitignore protocol fixture
check 0
while IFS= read -r literal; do
  printf '%s\n' "$literal" > protocol
  check 1
  git checkout -- protocol
  printf '%s\n' "$literal" > untracked
  check 1
  rm untracked
  printf '%s\n' "$literal" > protocol
  git add protocol
  printf 'safe\n' > protocol
  check 1
  git reset -q -- protocol
  git add protocol
  touch "$literal"
  check 1
  rm "$literal"
  touch "$literal"
  git add -- "$literal"
  rm "$literal"
  check 1
  git rm --cached -q -- "$literal"
done < "$patterns"
rm .secrets-patterns
check 2
touch .secrets-patterns
check 2
printf '\n' > .secrets-patterns
check 2
printf '  \n' > .secrets-patterns
check 2
cp "$patterns" .secrets-patterns
chmod 000 .secrets-patterns
check 2
chmod 600 .secrets-patterns
printf 'safe\n' > unreadable
chmod 000 unreadable
check 2
chmod 600 unreadable
rm unreadable
# A tracked working file hidden behind a locked directory is unreadable, not deleted.
mkdir locked
printf "safe\n" > locked/file
git add locked/file
head -n 1 "$patterns" > locked/file
chmod 000 locked
check 2
chmod 700 locked
rm locked/file
rmdir locked
git rm --cached -q locked/file
# Git can warn but exit zero when an untracked directory cannot be enumerated.
mkdir untracked-locked
head -n 1 "$patterns" > untracked-locked/file
chmod 000 untracked-locked
check 2
chmod 700 untracked-locked
rm untracked-locked/file
rmdir untracked-locked
mkdir ignored
cp "$patterns" ignored/private
ln -s ignored/private link
check 0
rm link
# A symlink ancestor must not expose an ignored tree through a tracked descendant.
mkdir tracked-dir ignored/nested
printf "safe\n" > tracked-dir/file
git add tracked-dir/file
rm -rf tracked-dir
cp "$patterns" ignored/nested/file
ln -s ignored/nested tracked-dir
check 0
rm tracked-dir
git rm --cached -q tracked-dir/file
# Ignored trees stay outside enumeration even when their directories are locked.
chmod 000 ignored
check 0
chmod 700 ignored
# A deleted tracked path must still have its index blob inspected.
printf 'safe\n' > deleted
git add deleted
rm deleted
check 0
# A NUL or newline in a path must not break Git enumeration.
printf 'safe\n' > $'odd\npath'
check 0
# Git and blob-read failures are errors, never clean.
mkdir fakebin
realgit=$(command -v git)
cat > fakebin/git <<SH
#!/bin/bash
if [ "\$1" = show ]; then exit 128; fi
exec "$realgit" "\$@"
SH
chmod +x fakebin/git
PATH="$work/fakebin:$PATH" check 2
rm -rf fakebin
mv .git git-unavailable
check 2
mv git-unavailable .git
# External files are the production contract; nested projects must not scan siblings.
mkdir -p nested/project neighbor
printf 'safe\n' > nested/project/input
head -n 1 "$patterns" > neighbor/private
git add nested/project/input neighbor/private
cd nested/project
ANKER_CHARGE_MONITOR_SECRETS_FILE="$patterns" bash "$scanner" > result
[ "$(cat result)" = clean ] || { echo 'FAIL: nested scope'; exit 1; }
rm result
head -n 1 "$patterns" > input
git add input
printf 'safe\n' > input
code=0
ANKER_CHARGE_MONITOR_SECRETS_FILE="$patterns" bash "$scanner" > result || code=$?
[ "$code" = 1 ] || { echo "FAIL: nested staged-only finding, got $code"; exit 1; }
! grep -F -f "$patterns" result
rm result
git add input
ln -s "$patterns" linked-patterns
code=0
ANKER_CHARGE_MONITOR_SECRETS_FILE="$PWD/linked-patterns" bash "$scanner" > result || code=$?
[ "$code" = 2 ] || { echo 'FAIL: linked patterns accepted'; exit 1; }
rm linked-patterns result
mkdir "$work/pattern-directory"
cp "$patterns" "$work/pattern-directory/patterns"
ln -s "$work/pattern-directory" "$work/pattern-directory-link"
code=0
ANKER_CHARGE_MONITOR_SECRETS_FILE="$work/pattern-directory-link/patterns" bash "$scanner" > result || code=$?
[ "$code" = 2 ] || { echo 'FAIL: linked patterns ancestor accepted'; exit 1; }
rm result
code=0
HOME="$work/test-home" bash "$scanner" > result || code=$?
[ "$code" = 2 ] || { echo 'FAIL: missing external default accepted'; exit 1; }
rm result
mkdir -p "$work/test-home/.config/anker-charge-monitor"
cp "$patterns" "$work/test-home/.config/anker-charge-monitor/secrets-patterns"
HOME="$work/test-home" bash "$scanner" > result
[ "$(cat result)" = clean ] || { echo 'FAIL: external default'; exit 1; }
rm result
echo 'PASS: secrets scanner regression suite'
