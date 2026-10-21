#!/bin/sh
# Construit l'IPK installable par le Homebrew Channel, et son manifeste webosbrew.
#   sh tools/package.sh            → dist/<id>_<version>_all.ipk + dist/<id>.manifest.json
# IPK = archive ar (debian-binary, control.tar.gz, data.tar.gz), comme ares-package.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
ID=$(python3 -c 'import json;print(json.load(open("app/appinfo.json"))["id"])')
VER=$(python3 -c 'import json;print(json.load(open("app/appinfo.json"))["version"])')
REPO=https://github.com/Smeagolworms4/lg-jellyfin-homeapp

sh tools/build.sh
cp dist/libhomepatch.so app/root/libhomepatch.so

W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
APPDIR="$W/data/usr/palm/applications/$ID"
mkdir -p "$APPDIR" "$W/control"
cp -r app/. "$APPDIR/"
find "$APPDIR" -name '__pycache__' -prune -exec rm -rf {} +
chmod 755 "$APPDIR/root/"*.sh "$APPDIR/root/flutter-client" "$APPDIR/root/jellyfeed.py"

SIZE=$(du -sk "$W/data" | cut -f1)
cat > "$W/control/control" <<CTRL
Package: $ID
Version: $VER
Section: misc
Priority: optional
Architecture: all
Installed-Size: $SIZE
Maintainer: Smeagolworms4 <smeagolworms4@gmail.com>
Description: JellyHome - Jellyfin sur l'accueil webOS
webOS-Package-Format-Version: 2
webOS-Packager-Version: x.y.x
CTRL
echo "2.0" > "$W/debian-binary"
# Chemins sans « ./ » en tête : le dépôt webosbrew les cherche tels quels (control, usr/palm/…)
( cd "$W/control" && tar --owner=0 --group=0 -czf ../control.tar.gz control )
( cd "$W/data" && tar --owner=0 --group=0 -czf ../data.tar.gz usr )
IPK="dist/${ID}_${VER}_all.ipk"
rm -f "$IPK"
( cd "$W" && ar rc "$DIR/$IPK" debian-binary control.tar.gz data.tar.gz )

SHA=$(sha256sum "$IPK" | cut -d' ' -f1)
cat > "dist/$ID.manifest.json" <<MAN
{
  "id": "$ID",
  "version": "$VER",
  "type": "web",
  "title": "JellyHome",
  "appDescription": "Ton Jellyfin sur l'accueil de la TV : bandeau et rangées avec tes covers, via Quick Connect. Root requis.",
  "iconUri": "$REPO/raw/main/app/icon-large.png",
  "sourceUrl": "$REPO",
  "rootRequired": true,
  "ipkUrl": "$REPO/releases/download/v$VER/${ID}_${VER}_all.ipk",
  "ipkHash": { "sha256": "$SHA" }
}
MAN
ls -la "$IPK" "dist/$ID.manifest.json"
