# Website repair execution image

This directory contains only the fixed runtime image, trusted controller, and upstream seccomp profile. Product snapshots and execution records belong to each task workspace. Credentials, generated products, and experiment data must not be added here.

The base image and Python Playwright package use 1.55.0, matching the project. Node is the executable distributed with that pinned package; the build records its version and verifies the built-in test runner. Runtime images run as UID/GID 1000, with a read-only root and product snapshot, private temporary storage, and no network except loopback.

Build with `docker build -t ai-agent-product/website-repair:pw-1.55.0-v1 runtime-images/website-repair`. Building an image does not enable the repair API. The controlled isolation probe must first produce a profile matching the current Runner, image ID, and configuration. No automatic container or snapshot deletion is allowed.
# Provenance

The base is the official Playwright Python 1.55.0 Noble multi-platform manifest,
pinned by digest in `Dockerfile`. The seccomp profile is based on
https://raw.githubusercontent.com/microsoft/playwright/v1.55.0/utils/docker/seccomp_profile.json
whose upstream SHA-256 is `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.
The local profile additionally allows the chroot syscall for Chromium's user
namespace sandbox under cap-drop ALL; it does not grant capabilities. All other
upstream rules remain intact. Its current hash is bound by the runtime fingerprint.
The Python package and browsers use the same version. Node comes from that package's
bundled driver, rather than the host. Real isolation probes passed on 2026-10-09 (Node v22.18.0, Playwright 1.55.0).
The image alone does not enable the repair entry; a matching controlled profile is required.
