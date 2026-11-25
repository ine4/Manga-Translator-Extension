# Windows qualification — 25 November 2026

**Status: live qualification passed for the default model on this workstation, with the Process Monitor capture explicitly waived by the owner.** The waiver is not a passing capture result. See the limits below. No page images, screenshots, image payloads, image prompts or browsing history are included in this report.

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
| Built extension background JS | `9ef90ad9efc4879637082ac86e66a4af9a55e225fb7b311060c605e0e3354d8b` |
| Built extension content script JS | `623babb68aa0ea2964e316e80b603edae72409eb8594118a8aab5616d8db6e4f` |
| Built extension popup JS | `1664e8e69e8929addb158b104225da977ed52d436135a23304bb3bd1b33993ab` |

Both release archives passed the installer's pinned hash checks before extraction.
Weights and runtime files remain ignored; no binary assets are committed.
Cargo.lock was generated and the dependency graph resolved, built and tested with
`--locked`; this does not constitute a dependency security audit.

## Fixes verified in the running application

- Completed Local AI defaults to fix extension compilation; fresh installations use Local AI, Auto source and English output. Existing cloud settings retain their mode and credentials.
- Fixed the detector's early return when the primary detector found zero bubbles: the existing secondary detector now gets its chance. The colored fixture had zero primary detections and two secondary detections; both were translated and rendered. A regression test covers this branch.
- Returned the actual request-memory bubble metadata from the pipeline. Tests can now check crop count, reading order and translated text rather than accepting an image alone.
- Replaced the smoke's generic one-off instruction with the actual production multimodal translation call. Its assertion still requires the known Spanish translations of two distinct generated images. The generic probe transcribed instead of translating; the production prompt succeeds. No model-specific generation change was needed.
- Restricted residency controls to the extension's own popup document, allowing its own page in a tab while rejecting website content-script senders.
- Added the Windows kill-on-close Job Object after reproducing an orphaned worker. Forced supervisor termination now closes the worker and releases CUDA allocations.
- Bounded setup downloads, retained official archive hash verification, committed Cargo.lock and used locked builds/tests. API path-output options return HTTP 422.

## Automated and live checks

The final sequential run completed successfully using Windows PowerShell 5.1, the restored backend Python and the current extension build:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File local-ai/test-manager.ps1 -PythonExe <backend-python>
powershell -NoProfile -ExecutionPolicy Bypass -File local-ai/test.ps1 -PythonExe <backend-python> -Live
<backend-python> local-ai/test_pages.py
```

- Four Rust tests; Python compilation; twelve backend tests; four model-catalog tests; five TypeScript lifecycle/routing/sender tests; npm clean installation, TypeScript and Vite production build; static image-file/browser-persistence guards.
- Mocked provider requests preserve BYO endpoint, key and multimodal format. Local requests discard cloud credentials/endpoints and disable proxy inheritance and redirects. Existing single/batch wire formats and mixed-success batches pass.
- Live production smoke: model load, two correct vision translations and release/unload.
- Actual backend Auto-language pages: Japanese, Korean, Chinese and English; two crops each, known greeting/thanks translations and correct top-to-bottom fixture order. Blank page: zero crops and unchanged pixels. Explicit Japanese selection also passes the advanced paths.
- Colored bubbles, outside text (including a third caption crop) and final upscale pass. PIL saves are permitted only to BytesIO and OpenCV image-file writes are trapped; no attempt occurred. Page image caches are empty after each request.
- `local-ai/test_runtime.py` passed against the running controller: two pins, competing-model rejection, loaded-model removal refusal, worker crash/reload, missing CUDA DLL failure with no residency, corrupt GGUF failure, inactive registered-model removal, then restored CUDA load/release. The temporarily hidden DLL was restored in finally.
- `local-ai/test_windows_supervision.py` previously passed for the same unchanged release binary: forced controller termination also terminates its actual child worker.
- Real WinForms handlers passed: installed catalog, GUI load/release, official HF file listing and populated weights/projector choices, invalid ID/repository rejection, default installer in a separate console while the UI timer continues. The owner confirmed the actual open manager's dropdown, status, buttons and HF controls are visible and usable without clipping.
- Default installation and HF file listing succeeded. An interrupted download/retry test verifies that incomplete files are not registered and that a completed retry records the exact revision. Invalid file/path catalog cases pass. The optional second compatible model was not installed.

The actual `start-backend.bat` launcher started the stack from the checkout path containing spaces. Backend warmup was healthy on CUDA. Controller 7678 and Python 7677 were reachable on loopback; worker 7679 was absent before demand. Setup did not consume a translation page, and startup did not download weights.

## Chrome acceptance

The exact built `extension/dist` was loaded unpacked in isolated Chrome for Testing 158.0.8127.88, with Developer mode enabled. Synthetic pages were generated and served from RAM using `local-ai/test_pages.py --serve`, with no-store responses. The rendered original and translated pages were inspected on screen/in-memory; no screenshots were saved.

- Fresh settings: Local AI enabled, Auto source, English output; catalog discovers the installed default without a key. A missing selected model is labeled not installed and rejected as Unknown local model; controller remains unloaded, with no cloud fallback.
- Seeded legacy cloud settings and synthetic legacy image-cache keys, then reloaded the extension. Cloud mode/key survived; legacy image-cache keys were deleted. Restored fresh defaults afterward.
- Site pin shared across two windows, same host/different paths: closing the first reader retained the worker; navigating the final reader to a similar nonmatching hostname unloaded it. Window pin/close also unloaded correctly.
- Background/minimized window: the 30-second alarm rescheduled while minimized and retained the model. Release all session pins cleared this browser's selections and alarm.
- Browser crash with a pin: controller released after the TTL; browser restart had empty session pins and retained Local AI settings. Extension reload recovery was also exercised.
- Twelve-crop translation in progress: close the last matching reader while its job runs; the worker remained alive, all twelve crops returned, and the worker unloaded after the job's last lease finished. Closing a reader does not abort the background job.
- The running scanner translated both a standard Japanese page and the formerly failing colored page. Actual rendered bubbles showed the known greeting and thanks in their expected positions, rather than relying only on the completion counter.
- Persistent extension storage contained only settings, no site names or image history. Site/window selections existed only in storage.session. After translation, extension-origin IndexedDB and Cache Storage were empty. Observed browser requests contained no external inference requests.

## Measurements

Individual observations with other desktop/GPU applications active; no filesystem-cache flush, controlled hardware benchmark or performance promise:

| Observation | Measured result |
| --- | --- |
| GPU before backend restoration/startup | 3,844 MiB |
| GPU before first smoke with detectors running | 4,781 MiB |
| First measured process load after installation | 64.150 s |
| Cache-warm reload after unpin, earlier run | 2.862 s |
| Final production smoke load | 3.959 s |
| Final smoke's two pinned vision calls | 0.410 s / 0.197 s |
| GPU after early smoke release | 4,725 MiB |
| GPU with an earlier single model pin | 10,510 MiB |
| GPU during the twelve-crop browser job | 12,502 MiB |
| Final advanced colored / outside / upscale pages | 9.220 s / 7.740 s / 8.760 s |
| Missing CUDA library rejection, separate fault run | 2.319 s |

Full-page times include detector/render work and on-demand reload; the smoke's warm calls are crop inference, not complete page timings. The first load was not a verified cache-cold disk measurement. SSD reload and OS-cache effects were observed without isolating them. GPU allocations returned near the concurrently changing desktop baseline after unload; reclaimable filesystem cache is not a deliberate model pin.

## Privacy evidence and remaining limits

The owner explicitly chose to skip the elevated Process Monitor capture after the desktop helper could not control its elevated window. No kernel-level all-process file/network trace is claimed. Evidence consists of code/static guards, API rejection tests, live PIL/OpenCV file-write traps, cache checks, browser storage inspection and browser request observation. These checks passed; they do not cover every OS or third-party write surface.

The optional outside-text detector was downloaded after the owner approved its gated official repository. Its local model SHA-256 is `6e242d79acf74dd74d189a201d6454479ab731de25b237c8960812cfaf5056b6`. No token was copied into source or chat. Optional Flux inpainting was not installed/authenticated: colored bubbles used the supported standard-fill fallback. A second model and arbitrary other GGUF/projector pairs are not qualified.

These generated fixtures verify known short translations, not general manga translation quality. Edge, other GPUs/drivers, true suspended/asleep browser scheduling and forced inference-timeout duration were not separately qualified. The installed NVIDIA driver was retained. OS pagefiles, crash dumps, browser-native caches and website behavior remain outside the application privacy guarantee.

Production npm audit reported zero advisories; five development-tooling advisories remain (one moderate, four high). No real images were sent to a cloud provider. No model/runtime binaries or generated page artifacts are committed.
