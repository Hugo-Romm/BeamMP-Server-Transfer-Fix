# BeamMP Server — cancellable resource transfers

An **unofficial, narrowly scoped modification of BeamMP Server 3.9.3**, maintained
by Hugo-Romm. This repository contains the complete upstream server source tree
with three modified files, the standalone patch, build instructions, dependency
provenance and license notices. It is not the official BeamMP release.

## Problem and change

On Linux, a resource download uses `sendfile`. If an authenticated client stops
draining its receive buffer, the server's send queue can fill. The original
`ClientKick` tries to synchronously send a framed kick reason **before** closing
the socket. A kick or shutdown during that transfer can therefore block; adding
a framed message to a raw ZIP stream is also inappropriate.

The change:

- Marks resource synchronization active before exposing the authenticated client;
  clears the flag only after synchronization completes.
- During synchronization, or server shutdown, disconnects directly instead of
  waiting to transmit a kick reason. Normal connected-player kicks retain their
  existing framed reason.
- Gives Linux file transfer a duplicated `CLOEXEC` socket descriptor protected by
  the socket lifetime mutex. Closing/shutting down cancels the same connection
  without allowing descriptor reuse to redirect file IO elsewhere. The transfer
  releases its duplicate and recognizes requested cancellation.

There is no increased shutdown timeout, fake successful save, protocol upgrade,
new service, mod change or automatic crash recovery. A downloading client may
see its connection close without receiving a textual kick reason.

An independent registration timer in our private integration previously started
while clients were downloading. That timer was corrected in the integration,
**without changing BeamMP**. It is not this patch. The historical incident that
motivated investigation lacked a thread capture: the tested blocking condition
does not establish the cause of every historical server crash.

## Exact base and provenance

| Item | Value |
| --- | --- |
| Upstream | [BeamMP/BeamMP-Server](https://github.com/BeamMP/BeamMP-Server) |
| Tag / commit | `v3.9.3` / `54f49d81e255d6021f6ebe04c85c6ecad4c7cef8` |
| This modification | `v3.9.3-hcoder.1` |
| vcpkg baseline | `5bf0c55239da398b8c6f450818c9e28d36bf9966` |
| Actually tested | Ubuntu 24.04, Linux ARM64, GCC 13, Release |
| Tested ELF SHA-256 | `796d2a272aeb017f20e520d55964398d2fa3fac9e824c7e7ec0b94e101add417` |

`provenance/build-lock.json` records the patch/source hashes and resolved static
dependency versions/ABIs. `upstream-submodules.txt` records the exact submodule
commits. `compiler-packages.txt` records the compiler container's package graph,
not an instruction to install unrelated server services.

Notable pinned dependencies: Boost 1.89.0, OpenSSL 3.6.0, Lua 5.3.5,
sol2 3.3.1, curl 8.17.0. The executable dynamically needs only the normal
Linux C/C++ runtime and math libraries. Windows/macOS/x86 builds have **not**
been tested. Source paths/build metadata may change binary bytes; the recorded
ELF hash identifies the tested artifact, not a promise of bit-identical rebuilds.

## Build

Prerequisites on the build host: Docker, network access to official Ubuntu and
GitHub/vcpkg dependency sources, and sufficient temporary space. Run on ARM64;
cross-emulated compilation is not part of the tested platform. The build uses
two compiler workers to bound temporary work, not a CPU quota for the game.

```sh
docker build --platform linux/arm64 -f Dockerfile.native -t beammp-transfer-fix .
docker create --name beammp-native-export beammp-transfer-fix /out/BeamMP-Server
docker cp beammp-native-export:/out/BeamMP-Server ./BeamMP-Server
docker cp beammp-native-export:/out/build-result.json ./build-result.json
docker rm beammp-native-export
docker image rm beammp-transfer-fix
```

The recipe uses a pinned Ubuntu image, exact compiler tool versions, the exact
upstream commit/submodules, the vcpkg manifest/baseline and this patch. It fails
if a pinned package or source is unavailable; it does not silently select a newer
server version. Ubuntu archive availability is an external requirement. Compiler
package transitive versions from the tested build are recorded separately.

`tools/compile.sh` contains the actual clone, patch, CMake/Ninja and strip sequence
used for the tested native build. `Dockerfile.native` packages that sequence as a
standalone public build without our private server image, credentials or bot.
The original tested compiler run used the same Ubuntu base/toolchain and an
existing private runtime as its starting image. On 2026-10-13 the standalone
public compiler stage was also cold-built successfully on ARM64, without that
private image. Its rebuilt ELF SHA-256 is
`01d8e669ab880f1054e71456416d22f1467a765c6afb92091b99910d263de26d`.
Source/patch hashes were checked by the recipe; this independently rebuilt
artifact is **not** the production ELF identified above. The scratch final stage
is for file export, not a runnable server image; `docker create` supplies an
explicit command and is not started. The compiler stage and file extraction were
actually exercised. Network/source availability remains an external requirement.
The rebuilt artifact additionally passed isolated stalled Stop (1.000 s) and
full-download Restart (13.709 s), exit 0 with shutdown hooks, no forced kill,
verified download hash and exactly one replacement run. A timeout of the SSH
output collector at the end of compilation was not treated as a successful
tool invocation: completion was verified in the produced image/output files and
these subsequent native tests. The disposable compiler image was then removed.

To apply only the patch to an existing clean upstream checkout:

```sh
git checkout 54f49d81e255d6021f6ebe04c85c6ecad4c7cef8
git submodule update --init --recursive
git apply --check /path/to/patches/cancellable-transfer.patch
git apply /path/to/patches/cancellable-transfer.patch
# Use the pinned build recipe/toolchain, not an arbitrary pre-existing binary.
```

The repository root already contains the patched sources: do not apply the diff
again there. To reverse it in that source tree:

```sh
git apply --reverse --check patches/cancellable-transfer.patch
git apply --reverse patches/cancellable-transfer.patch
```

Rebuild after reversal. Reverting source does not replace a running binary or
restore player data. For deployment, stop and confirm shutdown/save first, verify
your coherent recovery, replace/rebuild your own unit, and check the executable
hash and health. For rollback, restore the selected software **and associated
data/configuration checkpoint**, rather than mixing versions. No Docker image
or database from our private deployment is distributed here.

## Tests actually executed

All five cases ran the real patched ARM64 executable in isolated Docker with
fixture authentication and Discord, a read-only original ZIP of 40,041,297 bytes,
and the private integration's real stop/restart/save paths. They were **not human
BeamNG sessions**, public backend tests, or an overnight stability test.

| Case | Result | Total observed time |
| --- | --- | --- |
| Stop, receiver stalled | Exit 0, shutdown hook, no forced kill | 1.000 s |
| Restart, receiver stalled | Confirmed close, recovery/Git fixture, exactly one new run | 8.943 s |
| Kick, receiver stalled | Kick returned, server stayed alive, subsequent clean stop | 4.665 s |
| Stop after normal full download | Complete ZIP SHA-256 matched; confirmed close | 5.124 s |
| Restart after normal full download | ZIP hash matched, confirmed recovery/Git fixture, one new run | 8.745 s |

Totals include deliberate observation waits and integration maintenance, not just
native shutdown. Stalled cases read 65,536 bytes before stopping reception; the
native send queue held approximately 1.79 MB. The console still answered before
shutdown. The unmodified executable instead required SIGKILL after the unchanged
15-second integration grace period for stalled Stop/Restart. Neither that forced
close nor a mere exit 0 without a hook was certified as a successful save.

Both patched restart recovery files authenticated and the two isolated SQLite
bases passed integrity checks with their original row counts. No production
credentials, player names, databases or private integration code are included.
These application-level recovery tests are integration evidence, not a native
BeamMP world-save API invented by this patch.

`tools/transfer-client.py` provides the small reusable protocol probe used by
these tests. Run it **only against an isolated fixture** with a valid fixture
identity backend. It does not install that backend, start our private integration,
or reproduce our private SQLite/Git checks. See `--help`. The five recorded results
must not be confused with that standalone probe alone.

## License and source offer

BeamMP upstream copyright and GNU AGPL notices remain intact in `LICENSE` and
source headers. Hugo-Romm's three modified files carry dated modification notices;
the native modifications and accompanying scripts are provided under AGPL-3.0.
Upstream authorship is not reassigned. Dependencies retain their own licenses in
`third-party-licenses/`; their exact sources are available through the pinned
upstream submodules and vcpkg ports recorded in the build provenance.

This repository offers the corresponding native server sources. Users of a
deployment should receive a prominent link to the exact installed release/source
commit. [AGPL section 13](https://github.com/BeamMP/BeamMP-Server/blob/54f49d81e255d6021f6ebe04c85c6ecad4c7cef8/LICENSE#L478)
concerns network access to a modified program; no upstream PR or payment is needed.

The independently developed private server/bot repository, assets, mods, maps,
profiles, databases and secrets are not part of this public source export. No
private Git history was copied. This is an unofficial fix with limited measured
scope, not a guarantee that every BeamMP server or crash is fixed.
