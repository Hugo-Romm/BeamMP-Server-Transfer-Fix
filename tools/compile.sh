#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Hugo-Romm, 2026. Reconstruct exact upstream + native patch, never private data.
set -euo pipefail
workspace=${1:-/build};output=${2:-/out}
mkdir -p "$workspace" "$output"
cd "$workspace"
if [[ ! -d source/.git ]];then
 git clone --depth=1 --branch v3.9.3 --recurse-submodules --shallow-submodules https://github.com/BeamMP/BeamMP-Server.git source
fi
cd source
test "$(git rev-parse HEAD)" = 54f49d81e255d6021f6ebe04c85c6ecad4c7cef8
test "$(git -C vcpkg rev-parse HEAD)" = 5bf0c55239da398b8c6f450818c9e28d36bf9966
test "$(git -C deps/commandline rev-parse HEAD)" = 04952e4811e7d44708e64986bbc82fdc3485c800
test "$(git -C deps/toml11 rev-parse HEAD)" = f33ca743fb105bf54293cc822f56cf2794d15bf2
if [[ $(git -C vcpkg rev-parse --is-shallow-repository) == true ]];then git -C vcpkg fetch --unshallow --filter=blob:none;fi
if git diff --quiet -- include/Client.h src/Client.cpp src/TNetwork.cpp;then
 git apply --check /recipe/native-transfer.patch
 git apply /recipe/native-transfer.patch
else git apply --reverse --check /recipe/native-transfer.patch;fi
python3 - <<'PY'
import hashlib,json,pathlib
lock=json.load(open('/recipe/build-lock.json'))
assert hashlib.sha256(pathlib.Path('/recipe/native-transfer.patch').read_bytes()).hexdigest()==lock['patch_sha256']
for name,digest in lock['patched_sources'].items():assert hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()==digest,name
PY
export VCPKG_MAX_CONCURRENCY=2 VCPKG_BINARY_SOURCES=clear
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DVCPKG_TARGET_TRIPLET=arm64-linux -DBeamMP-Server_ENABLE_UNIT_TESTING=OFF
cmake --build build -j2
strip build/BeamMP-Server
install -m 0755 build/BeamMP-Server "$output/BeamMP-Server"
python3 - "$output" <<'PY'
import hashlib,json,pathlib,subprocess,sys
out=pathlib.Path(sys.argv[1]);elf=out/'BeamMP-Server'
result={'upstream':'54f49d81e255d6021f6ebe04c85c6ecad4c7cef8','native_version':'3.9.3','patch':'hcoder.1','sha256':hashlib.sha256(elf.read_bytes()).hexdigest(),'ldd':subprocess.check_output(['ldd',str(elf)],text=True).splitlines()}
(out/'build-result.json').write_text(json.dumps(result,indent=2)+'\n')
PY
