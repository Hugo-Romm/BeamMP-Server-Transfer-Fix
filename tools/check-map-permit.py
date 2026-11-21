"""Check map selection, release binding and the signature with an ephemeral test key."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs).stdout


def decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def check(source):
    deps = source / "build/vcpkg_installed/arm64-linux"
    stock = "/levels/west_coast_usa/info.json"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        cpp = root / "map.cpp"
        cpp.write_text('#include "HcodeRMapPermit.h"\n#include <iostream>\n'
                       'int main(int, char** a) { std::cout << HcodeRMapPermit::BuildMapRequest(a[1], a[2], a[3]); }\n')
        tool = root / "check"
        run("c++", "-std=c++17", "-I", source / "include", "-I", deps / "include", cpp,
            deps / "lib/libcrypto.a", "-ldl", "-pthread", "-o", tool)
        key, public, descriptor = (root / name for name in ("sign.pem", "pub.pem", "release.json"))
        assert run(tool, stock, descriptor, key).decode() == stock
        run("openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", key)
        run("openssl", "pkey", "-in", key, "-pubout", "-out", public)
        release = {"version": 1, "archiveSha256": "1" * 64, "manifestSha256": "2" * 64,
                   "contentKey": "3" * 64, "hosts": ["test.invalid"], "port": 30814}
        descriptor.write_text(json.dumps(release))
        other = "/levels/italy/info.json"
        assert run(tool, other, descriptor, key).decode() == other
        ids = set()
        for _ in range(2):
            request = run(tool, stock, descriptor, key).decode()
            prefix = stock + "?hcoderMapPermit="
            assert request.startswith(prefix)
            payload, signature = request[len(prefix):].split(".")
            sig_file = root / "signature.bin"
            sig_file.write_bytes(decode(signature))
            run("openssl", "dgst", "-sha256", "-verify", public, "-signature", sig_file, input=payload.encode())
            claims = json.loads(decode(payload))
            assert claims["mod"] == "hcoder-map" and claims["key"] == release["contentKey"]
            assert claims["manifest"] == release["manifestSha256"] and claims["sha"] == release["archiveSha256"]
            assert claims["hosts"] == release["hosts"] and claims["port"] == release["port"]
            assert claims["exp"] - claims["iat"] == 180
            ids.add(claims["jti"])
        assert len(ids) == 2


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve())
