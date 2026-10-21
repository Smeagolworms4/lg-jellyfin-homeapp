#!/bin/sh
# JellyHome — contrôle root (appelé par l'app via le Homebrew Channel, ou au boot).
#
#   install    hook de démarrage + activation        uninstall  tout retirer
#   start      pose l'interception, relance l'accueil stop       la retire
#   status     état en JSON                           refresh    rafraîchit Jellyfin
#   reload     régénère les règles et relance l'accueil (il garde ses rangées en cache)
#   boot       (hook webosbrew) attend le système puis start + service Jellyfin
#
# Rien n'est écrit dans le système hors du hook de boot : l'interception tient
# en bind-mounts, effacés à chaque redémarrage de la TV.
ROOT="$(cd "$(dirname "$0")" && pwd)"
DATA=/media/developer/jellyhome
BIN=/usr/bin/flutter-client
HOOK=/var/lib/webosbrew/init.d/60-jellyhome
HOME_RE="flutter-client -i com.webos.app.home"
export HOMEPATCH_DIR="$DATA"

mounted() { grep -q HOMEPATCH_PRELOAD "$BIN" 2>/dev/null; }

restart_home() {
  # SAM relance l'accueil (keepAlive) ; après des crashs il peut cesser : on le fait.
  pkill -f "$HOME_RE" 2>/dev/null
  sleep 3
  if ! pgrep -f "$HOME_RE" >/dev/null; then
    # luna-send -n 1 sans terminal rend la main avant d'envoyer : on attend.
    luna-send -i luna://com.webos.applicationManager/launch '{"id":"com.webos.app.home"}' >/dev/null 2>&1 &
    sleep 3; kill $! 2>/dev/null
  fi
}

mount_wrapper() {
  mounted && umount "$BIN"
  # /usr est partagé avec tous les jails d'apps : un montage posé sur $BIN s'y
  # propagerait. On auto-monte d'abord le binaire sur lui-même (inoffensif là où
  # ça se propage), on rend ce point privé, puis on monte le wrapper dessus.
  if ! grep -q " $BIN " /proc/mounts; then
    mount --bind "$BIN" "$BIN" && mount --make-private "$BIN" || return 1
  fi
  chmod 755 "$ROOT/flutter-client" "$ROOT/jellyfeed.py"
  mount --bind "$ROOT/flutter-client" "$BIN"
}

feeder() {
  pkill -f "jellyfeed.py daemon" 2>/dev/null
  setsid python3 "$ROOT/jellyfeed.py" daemon >> /tmp/jellyhome/jellyfeed.log 2>&1 < /dev/null &
}

mkdir -p "$DATA" /tmp/jellyhome

case "$1" in
  install)
    mkdir -p "$(dirname "$HOOK")"
    cat > "$HOOK" <<HOOKEOF
#!/bin/sh
# JellyHome — doit rendre la main immédiatement (sinon failsafe au boot suivant).
[ -x "$ROOT/jellyhomectl.sh" ] || { rm -f "\$0"; exit 0; }
setsid "$ROOT/jellyhomectl.sh" boot >/dev/null 2>&1 < /dev/null &
exit 0
HOOKEOF
    chmod 755 "$HOOK" "$0"
    "$0" start ;;
  boot)
    sleep 20
    [ -f "$DATA/stopped" ] || "$0" start ;;
  start)
    rm -f "$DATA/disabled" "$DATA/stopped" /tmp/jellyhome/launches
    python3 "$ROOT/jellyfeed.py" once >> /tmp/jellyhome/jellyfeed.log 2>&1
    mount_wrapper || { echo '{"ok":false,"error":"mount"}'; exit 1; }
    feeder
    restart_home
    "$0" status ;;
  stop)
    : > "$DATA/stopped"
    pkill -f "jellyfeed.py daemon" 2>/dev/null
    mounted && umount "$BIN"
    restart_home
    "$0" status ;;
  uninstall)
    "$0" stop >/dev/null
    rm -f "$HOOK"
    echo '{"ok":true}' ;;
  reload)
    python3 "$ROOT/jellyfeed.py" once >> /tmp/jellyhome/jellyfeed.log 2>&1
    mounted && restart_home
    "$0" status ;;
  refresh)
    pkill -USR1 -f "jellyfeed.py daemon" 2>/dev/null || python3 "$ROOT/jellyfeed.py" once >/dev/null 2>&1
    sleep 2; "$0" status ;;
  status)
    pid=$(pgrep -f "$HOME_RE" | head -1)
    patched=false; [ -n "$pid" ] && grep -q libhomepatch "/proc/$pid/maps" 2>/dev/null && patched=true
    feed=false; pgrep -f "jellyfeed.py daemon" >/dev/null && feed=true
    m=false; mounted && m=true
    hook=false; [ -f "$HOOK" ] && hook=true
    safe=false; [ -f "$DATA/disabled" ] && safe=true
    printf '{"ok":true,"mounted":%s,"homePatched":%s,"feeder":%s,"bootHook":%s,"failsafe":%s,"jellyfin":%s}\n' \
      "$m" "$patched" "$feed" "$hook" "$safe" "$(python3 "$ROOT/jellyfeed.py" status 2>/dev/null || echo null)" ;;
  *)
    echo "usage: $0 install|uninstall|start|stop|status|refresh|reload|boot"; exit 2 ;;
esac
