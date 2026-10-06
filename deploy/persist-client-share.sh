#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.'; exit 1; }
target=/mnt/ebir-starlight
[[ $(findmnt -rn -T "$target" -o FSTYPE) == cifs ]] || { echo 'Verify the SMB mount first.'; exit 1; }
[[ $(findmnt -rn -T "$target" -o SOURCE) == '//192.168.8.251/Starlight' ]] || { echo 'Unexpected share; stop.'; exit 1; }
test -f /etc/ebir-smb.credentials
chmod 600 /etc/ebir-smb.credentials
if ! awk '$2 == "/mnt/ebir-starlight" {found=1} END {exit !found}' /etc/fstab; then
  cp -p /etc/fstab "/etc/fstab.ebir-backup-$(date +%Y%m%d-%H%M%S)"
  printf '\n%s\n' '//192.168.8.251/Starlight /mnt/ebir-starlight cifs credentials=/etc/ebir-smb.credentials,vers=3.0,uid=1000,gid=1000,file_mode=0660,dir_mode=0770,nosuid,nodev,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30s 0 0' >> /etc/fstab
else
  echo 'An fstab entry already exists; it was not modified.'
fi
systemctl daemon-reload
echo 'Reboot mount entry configured. Current mount and existing services remain running.'
