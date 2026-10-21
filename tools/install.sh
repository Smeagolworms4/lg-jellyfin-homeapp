#!/bin/sh
# Installe l'IPK sur une TV rootée (SSH root par clé), sans passer par le dépôt.
#   sh tools/install.sh [IP]      (défaut 192.168.0.221)
set -e
TV="${1:-192.168.0.221}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH="ssh -o BatchMode=yes root@$TV"
IPK=$(ls "$DIR"/dist/*.ipk | head -1)
scp -q -o BatchMode=yes "$IPK" "root@$TV:/tmp/jellyhome.ipk"
# dev/install ne remplace pas toujours bien une app présente : réinstaller à neuf.
$SSH 'luna-send -i luna://com.webos.appInstallService/dev/install "{\"id\":\"com.smeagolworms4.jellyhome\",\"ipkUrl\":\"/tmp/jellyhome.ipk\",\"subscribe\":true}" > /tmp/jh-install.log 2>&1 & sleep 12; kill $! 2>/dev/null; grep -o "\"state\":\"[a-z ]*\"" /tmp/jh-install.log | tail -1'
