#!/bin/sh
# Cross-compile libhomepatch.so pour la TV (armv7, ABI softfp, glibc 2.35).
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$DIR/dist"
docker run --rm -v "$DIR:/src" -w /src debian:bookworm sh -c '
  command -v arm-linux-gnueabi-gcc >/dev/null || {
    apt-get update -qq && apt-get install -y -qq gcc-arm-linux-gnueabi >/dev/null; }
  arm-linux-gnueabi-gcc -shared -fPIC -O2 -Wall -march=armv7-a -mfpu=vfpv3-d16 -mfloat-abi=softfp \
    -fvisibility=default -o dist/libhomepatch.so \
    shim/homepatch.c shim/vendor/cJSON.c shim/vendor/cJSON_Utils.c -ldl -lpthread
  arm-linux-gnueabi-strip dist/libhomepatch.so
  chown '"$(id -u):$(id -g)"' dist/libhomepatch.so'
# La TV a glibc 2.35 : refuser tout symbole plus récent.
if objdump -T "$DIR/dist/libhomepatch.so" | grep -oE 'GLIBC_2\.(3[6-9]|[4-9][0-9])' | sort -u | grep .; then
  echo "ERREUR : symboles glibc trop récents pour la TV" >&2; exit 1
fi
ls -la "$DIR/dist/libhomepatch.so"
