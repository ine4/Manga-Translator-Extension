# Windows qualification — 25 November 2026

**Status: BLOCKED. Keep PR #1 in draft; do not merge.**

This records measured results for the qualification fixes on top of
`1d62d257998653d02302b2d6e2099daa43400b1d`. No page images, screenshots, image
payloads, prompts containing images, or browsing history are included here.

## Environment and artifacts

- Windows, x86_64 MSVC; checkout path contains spaces.
- NVIDIA GeForce RTX 4070 Ti SUPER, 16,376 MiB; driver 621.01.
- `rustc 1.100.0 (0ef1bc386 2026-11-09)`, host `x86_64-pc-windows-msvc`,
  LLVM 23.1.5; Cargo 1.100.0 (`3acc79c0c`, 2026-11-05).
- Existing Visual Studio 2022 C++ Build Tools were used; Rust stable was installed
  using the official rustup installer. The NVIDIA driver was already installed;
  it was not replaced or certified as the latest vendor release.
- Node 24.22.1 with npm; the app-bundled Node executable alone had no npm.
- Restored upstream v1.0.1 Python runtime: Python 3.13.11,
  PyTorch 2.10.0+cu130, CUDA available, huggingface_hub 1.13.0.
- Restored upstream v1.0.1 detector assets; existing tracked font packs were used.
  The model ZIP contains a top-level `models/` directory, so its correct extraction
  destination is `backend/`. README corrected accordingly.
- llama.cpp Windows CUDA 12.4 release b12644, engine commit `94f3af3d0`,
  built with Clang 22.1.8 for Windows x86_64.
- Qwen3-VL-4B-Instruct-GGUF revision
  `1cd86afb9a95c410a6038ab3b40d8b578c892266`, recorded by the Hugging Face
  installer in the ignored model manifest.

SHA-256 values:

| Artifact | SHA-256 |
| --- | --- |
| Official engine ZIP, b12644 CUDA 12.4 | `b72264d4a3222828ce9c6a818e38766797948f8503742b217937bfc823929a5d` |
| Official CUDA runtime ZIP | `8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6` |
| Installed `llama-server.exe` | `b3fe40f4032b73366a82ac4a726a0cec3da6a9b3383dd3ecef698035b7e6c438` |
| Built `manga-local.exe` with Windows Job Object | `5914ba4fb68fc7c63a31c9ead298a3ea5b2023a2d5b1a90f07f7df1c6ffa6eb5` |
| Q4_K_M weights | `66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a` |
| Q8_0 projector | `30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d` |
| Cargo.lock | `02c41fddab1ed50f5eedd7a6b5b596939c1ef4c90400071fb1b4352713d973fc` |
| Built extension background JS | `e18f262a101dcd0f0292daad6108d942b8455a6ebe53368e5fe44327adddf4361` |
| Built extension content script JS | `623babb68aa0ea2964e316e80b603edae72409eb8594118a8aab5616d8db6e4f` |
| Built extension popup JS | `1664e8e69e8929addb158b104225da977ed52d436135a23304bb3bd1b33993ab` |

Both release archives passed the installer's pinned hash checks before extraction.
Weights and runtime files remain ignored; no binary assets are committed.
Cargo.lock was generated and the dependency graph resolved, built and tested with
`--locked`; this does not constitute a dependency security audit.

## Passing checks and fixes

`powershell -NoProfile -ExecutionPolicy Bypass -File local-ai/test.ps1
-PythonExe <checkout>\backend\runtime\python.exe` passed its non-live stages:

- Four Rust unit tests.
- Python source compilation, excluding installed runtimes, models and build trees.
- Eight backend tests, including mocked cloud/local configuration and single/batch
  response formats, mixed-success batches, and HTTP 422 for path-output options.
- Three Hugging Face catalog tests.
- `npm ci`, TypeScript compilation and Vite production build.
- Four pure TypeScript lifecycle/routing tests and the supplied static privacy guards.

The initial extension compilation failed because content-script defaults omitted
`localAiEnabled` and `localModel`. Those defaults now include Local AI and Auto
source, with legacy settings remaining in cloud mode. This is build-tested;
fresh-install/upgrade behavior still needs actual browser qualification.

Windows PowerShell's archive request stalled without transferring bytes. Setup now
uses bounded curl downloads, retaining SHA-256 verification and checked staging
cleanup. Setup completed, installing only the runtime/model dependencies. The
Hugging Face file-list CLI also returned the official repository's five GGUF files.

The actual Python backend reported all four detector/OCR/upscale warmup components
ready on CUDA and `/health` returned healthy at 127.0.0.1:7677. The Rust controller
reported the default installed, engine available, zero leases, and no model loaded
at 127.0.0.1:7678. No translation worker listened on 7679 before demand.

Forced termination of the original Rust supervisor left an inference worker alive.
The fix assigns the controller to a kill-on-close Windows Job Object before it
spawns children. The rebuilt release was tested with an actual default-model pin:
forced controller termination closed the worker port and GPU memory returned to
4,709 MiB. The separate repeatable check is:

```powershell
# Stop the stack first: the test refuses occupied controller/worker ports.
backend\runtime\python.exe local-ai\test_windows_supervision.py
```

The test owns its controller process and sends no images. Normal page-lease
release also unloaded the worker. Other crash/cancellation scenarios remain open.

## Measurements and live failure

These are individual observations with other desktop/GPU applications active,
not controlled benchmarks or guarantees. No OS filesystem cache was flushed.

| Observation | Measured result |
| --- | --- |
| GPU memory before backend restoration/startup | 3,844 MiB |
| GPU memory immediately before first live smoke, detector backend running | 4,781 MiB |
| First measured model process load after installation | 64.150 s |
| First smoke's two warm vision requests | 0.226 s / 0.114 s |
| GPU memory after initial smoke release | 4,725 MiB |
| GPU memory with a later model pin | 10,510 MiB |
| Later model reload with warm filesystem cache | 2.862 s |
| Final stricter smoke load / first inference | 3.118 s / 0.298 s |

**The initial smoke's success was a false positive for translation quality:** it
accepted any non-empty response. The model transcribed the synthetic source
instead of performing the requested Spanish translation. A clearer system
instruction and a larger-text fixture did not resolve this. Text-only translation
worked in a separate probe, so CUDA generation alone is not the missing capability.
The smoke now checks the known synthetic Spanish translation. The final `-Live`
run failed this assertion with exit 1 and released its pin in `finally`.
Do not weaken the assertion to make qualification pass.

Four separate generated two-bubble pages were sent through the actual backend
with Auto source and English output, entirely in RAM:

| Generated fixture | Detected language | Request wall time | API result |
| --- | --- | --- | --- |
| Japanese | Japanese | 5.135 s | Image returned |
| Chinese | Chinese | 4.032 s | Image returned |
| Korean | Korean | 4.051 s | Image returned |
| English | English | 3.997 s | Image returned |

These timings include each page's on-demand model reload; they are not pinned-page
benchmarks. Bubble metadata was empty in every response. No claim is made about
crop count, reading order, translation fidelity, or the rendered images. No image
or response payload was saved. Cold disk load versus OS-cache load and sustained
pinned-page timings still require a controlled qualification run.

## Outstanding merge gates

- Fix and qualify default-model vision translation; the stricter live smoke is red.
- Load the built extension and inspect the exact running build on screen. Chrome
  reached Developer mode and the unpacked-folder chooser, but installation and
  popup behavior were not verified. UI captures later returned an unrelated active
  application instead of the requested Chrome window. The manager processes were
  started but no manager window was reliably observed. Neither visual acceptance
  requirement is marked passed.
- Run the complete real multi-tab/window/session lease matrix, in-flight close,
  TTL/crash, extension reload/restart, competing-model and missing-CUDA cases.
- Qualify GUI install/list/pin/release/remove and incomplete-download recovery on
  Windows PowerShell 5.1; CLI listing and default installation are only partial evidence.
- Run Process Monitor and network observation across success/failure/batch,
  colored bubbles, outside text and upscale. Static guards and routing mocks do
  not prove absence of image writes, persistent browser keys or external inference.
- Qualify explicit source selection, reading order, crop counts, blank pages,
  rendering and translation fidelity using permitted fixtures on screen.
- npm reported five dependency advisories (one moderate, four high); these were
  not audited or repaired in this batch.

The driver was not upgraded, no additional model was installed, and no provider
received real images. This run does not satisfy the complete acceptance checklist.
