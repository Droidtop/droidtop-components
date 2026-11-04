#!/usr/bin/env python3
"""Verifies a detached droidtop JWS (see sign_jws.py) against a root public key (droidtop root for official, gamegrab root for gamegrab).
Usage: verify_jws.py <typ> <content file> <jws file> <root.pub> [required SAN URN ...]
Checks: ES256 over the exact content bytes with the x5c leaf's key; the leaf is signed by Core's key
(ECDSA or RSA), CA:FALSE, digitalSignature, carries the EKU for the typ, and names each given URN.
Expiry is not checked (droidtop ignores it). Exits non-zero on any failure."""
import base64, datetime, os, sys
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, utils

EKU_BASE = "2.25.230248497294207031301727532441854392946"
EKU = {"droidtop-plugin+jws": EKU_BASE + ".1", "droidtop-catalog+jws": EKU_BASE + ".2"}

# Key rotation 2026-11-04 (Droidtop/tracker#876, #550): droidtop-root.pub is the new root. The root it replaced,
# droidtop-root-previous.pub beside it, is also accepted until the same instant droidtop itself stops trusting it
# (DroidtopSigningRoot.OLD_ROOT_EXPIRES_AT): the owner's "Pin the old key for 7 days, then expire it".
PREVIOUS_ROOT_EXPIRES_AT = datetime.datetime(2026, 11, 11, 23, 59, 59, tzinfo=datetime.timezone.utc)

def roots_in_force(root_path, now=None):
    """The root PEMs to try for [root_path]: it, then droidtop-root-previous.pub beside it until the expiry instant."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    roots = [open(root_path, "rb").read()]
    previous = os.path.join(os.path.dirname(root_path), "droidtop-root-previous.pub")
    if os.path.basename(root_path) == "droidtop-root.pub" and now <= PREVIOUS_ROOT_EXPIRES_AT and os.path.exists(previous):
        roots.append(open(previous, "rb").read())
    return roots

def verify_any(typ, content, jws, root_pems, urns=()):
    error = None
    for pem in root_pems:
        try:
            return verify(typ, content, jws, pem, urns)
        except Exception as e:  # the next root may be the one that issued the leaf
            error = error or e
    raise error

def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

def verify(typ, content, jws, core_pem, urns=()):
    import json
    h, mid, sig = jws.strip().split(".")
    if mid:
        raise ValueError("payload is not detached")
    header = json.loads(b64d(h))
    if header.get("alg") != "ES256" or header.get("typ") != typ or "crit" in header:
        raise ValueError("bad header %r" % header)
    leaf = x509.load_der_x509_certificate(base64.b64decode(header["x5c"][0]))
    core = serialization.load_pem_public_key(core_pem)
    if isinstance(core, ec.EllipticCurvePublicKey):
        core.verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm))
    else:
        core.verify(leaf.signature, leaf.tbs_certificate_bytes, padding.PKCS1v15(), leaf.signature_hash_algorithm)
    bc = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value
    ku = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
    eku = [o.dotted_string for o in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value]
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.UniformResourceIdentifier)
    if bc.ca or not ku.digital_signature or ku.key_cert_sign or EKU[typ] not in eku:
        raise ValueError("leaf profile wrong")
    for u in urns:
        if u not in san:
            raise ValueError("leaf lacks %s (has %s)" % (u, san))
    raw = b64d(sig)
    if len(raw) != 64:
        raise ValueError("signature not raw R||S")
    signing_input = h.encode() + b"." + base64.urlsafe_b64encode(content).rstrip(b"=")
    leaf.public_key().verify(utils.encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                             signing_input, ec.ECDSA(hashes.SHA256()))
    return san

if __name__ == "__main__":
    typ, cpath, jpath, corepath, *urns = sys.argv[1:]
    san = verify_any(typ, open(cpath, "rb").read(), open(jpath).read(), roots_in_force(corepath), urns)
    print("OK", " ".join(san))
