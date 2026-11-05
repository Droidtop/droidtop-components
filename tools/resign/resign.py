#!/usr/bin/env python3
"""Re-signs a published droidtop plugin bundle in place, and verifies one as droidtop does.

  resign.py resign <bundle in> <bundle out> <key.pem> <leaf.pem>
      Same members, same order, same metadata; manifest.json and every payload byte untouched. manifest.jws is
      replaced (or added when missing), manifest.sig and origin.cert are replaced when the bundle had them, exactly
      as each repository's sign.sh makes them (openssl SHA-256 over manifest.json, base64; detached ES256 JWS, typ
      droidtop-plugin+jws, x5c = the leaf; origin.cert = the leaf PEM).
  resign.py verify <bundle> <root.pub.pem> [expected-leaf.pem]
      ChainSignature.kt's rules: leaf signed by the root, EKU <arc>.1, not a CA, digital signature only, SAN names
      urn:droidtop:origin:<manifest origin> and covers the manifest id, detached JWS over manifest.json verifies;
      manifest.sig and origin.cert, when present, agree with the leaf.
  resign.py same-payload <bundle a> <bundle b>
      Every member except the three signature files is identical (name, order, metadata, bytes).
  resign.py check-keyjson <droidtop-plugin-key.json> <root.pub.pem>
      The published root certificate in a gamegrab droidtop-plugin-key.json is the root key.
  resign.py verify-jws <typ> <content> <jws> <root.pub.pem> <expected SAN uri>
      The same chain check for a catalog (typ droidtop-catalog+jws, EKU <arc>.2).
Prints no secret: only certificate and key fingerprints."""
import base64, hashlib, io, json, lzma, subprocess, sys, tarfile
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

ARC = "2.25.230248497294207031301727532441854392946"
PURPOSE = {"droidtop-plugin+jws": ARC + ".1", "droidtop-catalog+jws": ARC + ".2"}
SIGNATURE_FILES = ("manifest.sig", "manifest.jws", "origin.cert")


def b64u(data): return base64.urlsafe_b64encode(data).rstrip(b"=")
def unb64u(text): return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
def sha(data): return hashlib.sha256(data).hexdigest()
def spki(key): return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def read_bundle(path):
    members = []
    with tarfile.open(path, "r:xz") as t:
        for m in t.getmembers():
            members.append((m, t.extractfile(m).read() if m.isreg() else None))
    return members


def by_name(members): return {m.name: d for m, d in members}


def make_jws(typ, content, key, leaf):
    x5c = [base64.b64encode(leaf.public_bytes(serialization.Encoding.DER)).decode()]
    header = b64u(json.dumps({"alg": "ES256", "typ": typ, "x5c": x5c}, separators=(",", ":")).encode())
    signing_input = header + b"." + b64u(content)
    r, s = utils.decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    return header + b".." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def resign(src, dst, key_path, leaf_path):
    key = serialization.load_pem_private_key(open(key_path, "rb").read(), None)
    leaf_pem = open(leaf_path, "rb").read()
    leaf = x509.load_pem_x509_certificate(leaf_pem)
    members = read_bundle(src)
    names = [m.name for m, _ in members]
    manifest = by_name(members)["manifest.json"]
    # manifest.sig as sign.sh: openssl dgst -sha256 -sign | base64 -w0
    sig = base64.b64encode(subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path], input=manifest,
                                          capture_output=True, check=True).stdout)
    new = {"manifest.sig": sig, "manifest.jws": make_jws("droidtop-plugin+jws", manifest, key, leaf), "origin.cert": leaf_pem}
    out = []
    for m, data in members:
        if m.name in new:
            data = new[m.name]
            m.size = len(data)
        out.append((m, data))
    added = ""
    if "manifest.jws" not in names:
        template = next(m for m, _ in members if m.name == "manifest.json")
        info = tarfile.TarInfo("manifest.jws")
        info.mode = 0o600
        info.uid, info.gid, info.uname, info.gname, info.mtime = template.uid, template.gid, template.uname, template.gname, template.mtime
        info.size = len(new["manifest.jws"])
        at = names.index("manifest.json") + 1 + (1 if "manifest.sig" in names else 0)
        out.insert(at, (info, new["manifest.jws"]))
        added = " (manifest.jws was missing and is added)"
    with lzma.open(dst, "wb", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, preset=9 | lzma.PRESET_EXTREME) as xz:
        with tarfile.open(fileobj=xz, mode="w", format=tarfile.GNU_FORMAT) as t:
            for m, data in out:
                t.addfile(m, io.BytesIO(data) if data is not None else None)
    print("resigned", len(out), "members" + added)


def check_chain(typ, content, jws, root):
    """Returns (leaf cert or None, problems)."""
    h, p, s = jws.strip().split(".")
    if p:
        return None, ["JWS is not detached"]
    hdr = json.loads(unb64u(h))
    bad = []
    if "crit" in hdr: bad.append("crit header")
    if hdr.get("typ") != typ: bad.append("typ " + str(hdr.get("typ")))
    if hdr.get("alg") != "ES256": bad.append("alg " + str(hdr.get("alg")))
    x5c = hdr.get("x5c") or []
    if not 1 <= len(x5c) <= 3:
        return None, bad + ["x5c length"]
    chain = [x509.load_der_x509_certificate(base64.b64decode(c)) for c in x5c]
    leaf = chain[0]
    if leaf.version != x509.Version.v3: bad.append("leaf not v3")
    if leaf.signature_algorithm_oid.dotted_string != "1.2.840.10045.4.3.2": bad.append("leaf sig alg")
    try:
        if leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca: bad.append("leaf is a CA")
    except x509.ExtensionNotFound:
        pass
    try:
        ku = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        return leaf, bad + ["no key usage"]
    if not ku.digital_signature: bad.append("no digitalSignature")
    if ku.key_cert_sign: bad.append("leaf may sign certificates")
    ekus = [o.dotted_string for o in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value]
    if PURPOSE[typ] not in ekus: bad.append("EKU missing " + PURPOSE[typ])
    if any(spki(c.public_key()) == spki(root) for c in chain): bad.append("chain carries the root")
    for a, b in zip(chain, chain[1:]):
        try: b.public_key().verify(a.signature, a.tbs_certificate_bytes, ec.ECDSA(hashes.SHA256()))
        except Exception: bad.append("chain broken")
    try: root.verify(chain[-1].signature, chain[-1].tbs_certificate_bytes, ec.ECDSA(hashes.SHA256()))
    except Exception: bad.append("chain does not lead to the root")
    sig = unb64u(s)
    try:
        leaf.public_key().verify(utils.encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                                 (h + "." + b64u(content).decode()).encode(), ec.ECDSA(hashes.SHA256()))
    except Exception:
        bad.append("signature does not verify")
    return leaf, bad


def uris(leaf):
    return leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.UniformResourceIdentifier)


def covers(leaf, plugin_id):
    entries = [u[len("urn:droidtop:plugin:"):] for u in uris(leaf) if u.startswith("urn:droidtop:plugin:")]
    if not entries:
        return True
    return any((plugin_id.startswith(e[:-1]) and len(plugin_id) > len(e) - 1) if e.endswith(".*") else e == plugin_id for e in entries)


def load_root(path): return serialization.load_pem_public_key(open(path, "rb").read())


def verify(bundle, root_path, expected=None):
    files = by_name(read_bundle(bundle))
    manifest = files["manifest.json"]
    mj = json.loads(manifest)
    leaf, bad = check_chain("droidtop-plugin+jws", manifest, files["manifest.jws"].decode(), load_root(root_path))
    if leaf is None:
        raise SystemExit("FAIL " + "; ".join(bad))
    if "urn:droidtop:origin:" + mj["origin"] not in uris(leaf): bad.append("SAN lacks origin " + mj["origin"])
    if not covers(leaf, mj["id"]): bad.append("SAN does not cover id " + mj["id"])
    if "manifest.sig" in files:
        try: leaf.public_key().verify(base64.b64decode(files["manifest.sig"]), manifest, ec.ECDSA(hashes.SHA256()))
        except Exception: bad.append("manifest.sig does not verify under the leaf")
    if "origin.cert" in files and x509.load_pem_x509_certificate(files["origin.cert"]) != leaf: bad.append("origin.cert differs from the x5c leaf")
    if expected and x509.load_pem_x509_certificate(open(expected, "rb").read()) != leaf: bad.append("leaf differs from the provisioned leaf")
    if bad:
        raise SystemExit("FAIL " + "; ".join(bad))
    print("OK", mj["id"], "origin", mj["origin"], "leaf-key", sha(spki(leaf.public_key()))[:16],
          "sig" if "manifest.sig" in files else "no-sig", "cert" if "origin.cert" in files else "no-cert")


def same_payload(a, b):
    ma, mb = read_bundle(a), read_bundle(b)
    keep = lambda ms: [(m.name, m.type, m.mode, m.uid, m.gid, m.uname, m.gname, m.mtime, d) for m, d in ms if m.name not in SIGNATURE_FILES]
    if keep(ma) != keep(mb):
        raise SystemExit("FAIL payload members differ")
    print("OK payload identical; signature members old:", ",".join(m.name for m, _ in ma if m.name in SIGNATURE_FILES),
          "new:", ",".join(m.name for m, _ in mb if m.name in SIGNATURE_FILES))


def check_keyjson(path, root_path):
    doc = json.load(open(path))
    cert = x509.load_pem_x509_certificate(doc["certificate"].encode())
    if spki(cert.public_key()) != spki(load_root(root_path)):
        raise SystemExit("FAIL " + path + " does not hold the root key")
    print("OK", path, "origin", doc["origin"], "root", sha(spki(cert.public_key()))[:16])


def verify_jws(typ, content_path, jws_path, root_path, san):
    leaf, bad = check_chain(typ, open(content_path, "rb").read(), open(jws_path).read(), load_root(root_path))
    if leaf is not None and san not in uris(leaf): bad.append("SAN lacks " + san)
    if bad:
        raise SystemExit("FAIL " + "; ".join(bad))
    print("OK", jws_path, "leaf-key", sha(spki(leaf.public_key()))[:16], "san", san)


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"resign": resign, "verify": verify, "same-payload": same_payload, "check-keyjson": check_keyjson, "verify-jws": verify_jws}[cmd](*args)
