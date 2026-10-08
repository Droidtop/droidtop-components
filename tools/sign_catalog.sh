#!/bin/bash
# Signs <out>/catalog.json for droidtop (docs in README.md, "Catalog signature").
#   CATALOG_SIGNING_KEY   the catalog key, a PEM P-256 private key (repository secret)
#   CATALOG_SIGNING_CERT  its certificate, issued by droidtop's master key (repository secret)
# Writes <out>/catalog.json.sig (base64 DER ECDSA/SHA-256 over the exact file bytes) and
# <out>/catalog.cert, and checks the signature against the key the certificate names before
# anything is published. The private key only ever exists in a 0600 file under RUNNER_TEMP.
set -eu
out=${1:?usage: sign_catalog.sh <out dir>}
: "${CATALOG_SIGNING_KEY:?}" "${CATALOG_SIGNING_CERT:?}"
tmp=$(mktemp -d "${RUNNER_TEMP:-/tmp}/catalog-sign.XXXXXX")
trap 'rm -rf -- "${tmp:?}"' EXIT
umask 077
printf '%s\n' "$CATALOG_SIGNING_KEY" > "$tmp/key.pem"
openssl dgst -sha256 -sign "$tmp/key.pem" "$out/catalog.json" | base64 -w0 > "$out/catalog.json.sig"
printf '%s\n' "$CATALOG_SIGNING_CERT" > "$out/catalog.cert"
python3 - "$out/catalog.cert" "$tmp/pub.der" <<'PY'
import base64, json, sys
cert = json.load(open(sys.argv[1]))
assert cert.get('formatVersion') == 1 and cert.get('catalogs'), 'catalog.cert is not a catalog certificate'
open(sys.argv[2], 'wb').write(base64.b64decode(cert['publicKeySpki']))
PY
base64 -d "$out/catalog.json.sig" > "$tmp/sig.der"
openssl dgst -sha256 -verify "$tmp/pub.der" -keyform DER -signature "$tmp/sig.der" "$out/catalog.json"
