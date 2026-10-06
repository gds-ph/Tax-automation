#!/usr/bin/env bash
# Run interactively on Linux: sudo bash deploy/mount-client-share.sh
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo.' >&2; exit 1; fi
target=/mnt/ebir-starlight
credentials=/etc/ebir-smb.credentials
if ! command -v mount.cifs >/dev/null; then
  apt-get update
  apt-get install -y cifs-utils
fi
install -d -m 0755 "$target"
if ! mountpoint -q "$target"; then
  if [[ ! -f $credentials || ${1:-} == --update-credentials ]]; then
    read -r -p 'SMB username: ' smb_user
    read -r -p 'SMB domain (blank if none): ' smb_domain
    read -r -s -p 'SMB password: ' smb_password
    printf '\n'
    [[ -n $smb_user && -n $smb_password ]] || { echo 'Username/password required.'; exit 1; }
    umask 077
    printf 'username=%s\npassword=%s\n' "$smb_user" "$smb_password" > "$credentials"
    if [[ -n $smb_domain ]]; then printf 'domain=%s\n' "$smb_domain" >> "$credentials"; fi
    unset smb_password
  fi
  chmod 600 "$credentials"
  if ! mount -t cifs '//192.168.8.251/Starlight' "$target" \
    -o "credentials=$credentials,vers=3.0,uid=1000,gid=1000,file_mode=0660,dir_mode=0770,nosuid,nodev"; then
    echo 'Mount failed. To replace the saved login, rerun this script with --update-credentials.' >&2
    exit 1
  fi
fi
test -d "$target/Starlight offline/CLIENT" || { echo 'Expected CLIENT folder not found; stop here.'; exit 1; }
echo 'Share mounted. Credentials were saved root-only and were not printed.'
echo 'Reboot persistence will be configured after the mount is verified.'
