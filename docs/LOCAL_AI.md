# Local AI — Windows setup and Codex handoff

This change introduces a local-first translator while preserving the existing BYO-cloud workflow. The default model has been qualified on the Windows/CUDA workstation and Chrome build recorded below; other environments still need qualification.

See [Windows qualification, 25 November 2026](LOCAL_AI_QUALIFICATION.md) for actual results and hashes. The production vision smoke, Chrome lifecycle checks and GUI checks pass. The owner explicitly waived the elevated Process Monitor capture; this is not reported as a passing capture.

## Installation

1. Install current NVIDIA drivers, Rust stable MSVC toolchain ([rustup](https://rustup.rs/)), Visual Studio C++ Build Tools, Python/runtime and Node 22+. Restore the existing backend detection models and font assets described in the README.
2. Run `setup-local-ai.bat` (or choose option 5 in `setup.bat`). It builds the Rust controller, verifies and extracts two official llama.cpp CUDA 12.4 release archives (b12644), and downloads the default model through the existing Hugging Face Python client. No translation image is used during setup.
3. Run `start-backend.bat`. The stack starts the Rust controller at loopback port 7678 and the existing Python backend at port 7677. The inference worker on port 7679 is **not** started until a translation or pin requests the model.
4. Build the browser extension: `cd extension; npm ci; npm run build`. In Chrome/Edge 120+, open the extensions page, enable Developer mode, Load unpacked, select `extension/dist`.
5. New users default to Local AI with source Auto and English output. Existing settings retain the cloud mode until the user enables Local AI. The Local AI tab discovers the installed model catalog automatically; no API key, endpoint, or Ollama/LM Studio is required.

The normal backend image detector still needs its existing ML dependencies. Local AI adds only the translation VLM; it does not install all pre-existing model assets. For true offline use, download all detector/font/model dependencies first. `start-backend.bat` does not download model weights or preload translation VRAM.

## Default model and dependencies

| Component | Source |
|---|---|
| Default VLM | [Qwen/Qwen3-VL-4B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF) |
| Weights | Qwen3VL-4B-Instruct-Q4_K_M.gguf (~2.5 GB) |
| Vision encoder | mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf |
| GPU engine | [llama.cpp CUDA b12644](https://github.com/ggml-org/llama.cpp/releases/tag/b12644) |
| Rust controller | Axum, Tokio, Reqwest, Serde, UUID |
| Download | [huggingface_hub](https://github.com/huggingface/huggingface_hub) |
| Windows GUI | Built-in PowerShell / Windows Forms |

Rust owns the catalog, model loading decisions, process lifecycle, leases, local API and request routing. llama.cpp owns the actual CUDA model-loading/inference kernels; this is not an all-Rust tensor implementation. This choice reuses a maintained GGUF vision engine instead of implementing a CUDA VLM from scratch. The backend wrapper reuses the established multimodal request format. GGUF files are memory-mapped by the inference engine by default; Windows may retain reclaimable filesystem cache in RAM after unload. No deliberate RAM pin is maintained when there is no demand. Do not promise measured loading time until qualified.

The runtime and weights are ignored by git. No model binaries are in this PR. The installer verifies official release archive hashes. Hugging Face installs resolve a revision SHA and record the exact downloaded revision in model.json. Model compatibility still requires an actual local inference test.

## Residency behavior

| State | Behavior |
|---|---|
| Startup / no request | Controller running, translator weights on SSD, no inference worker |
| Translate a page | Acquire page lease, load selected model into CUDA VRAM, detect source language if Auto, run all image crops, release after page finishes |
| Site pin | Click Keep in VRAM while this site is open. Keep model loaded while any tab in any window has the same exact hostname; paths and query strings are irrelevant |
| Window pin | Click Keep in VRAM while this window is open. Keep while any tab remains in that window |
| Last matching tab/window closes or navigates away | Browser releases lease; after any running page finishes the worker exits and its model VRAM is freed |
| GUI session pin | Load for GUI session; release when GUI closes or Release is clicked |
| Browser/service worker crash | Unrefreshed browser/GUI leases expire after 90 seconds; abandoned page job leases expire after 30 minutes |
| Multiple models | Only one worker is resident; conflicting active model requests fail explicitly instead of thrashing |
| Disable Local AI | Clears browser pins and returns to configured BYO-cloud workflow |

Site/window selections are stored in Chrome's volatile storage.session (not storage.local) so Manifest V3 service worker suspension does not lose them. Browser session restart clears them. The controller sees only a random lease ID, selected model ID and keep/release boolean. No URL, hostname or browsing history is sent to the controller. The tabs permission is needed to see matching tabs across all windows; alarms refresh the lease at 30-second intervals. An active page owns a separate lease so closing a reader cannot interrupt its in-flight request. Chrome suspended/asleep or overloaded inference can delay lease reconciliation; qualify with actual multi-tab tests.

## Windows model manager

Run `start-local-model-manager.bat` while the stack is running. The simple WinForms GUI lists models, installation status, current residency and active lease count. It can load/release a GUI session pin, install the default model, remove a model that isn't active, or list GGUF files in a Hugging Face model repository and install a selected compatible weights/projector pair. Downloads run in a separate console.

### Add / remove using CLI

From the repository root (use the same Python executable as start-backend.bat):

```powershell
python local-ai/model_manager.py files https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF
python local-ai/model_manager.py install-default
python local-ai/model_manager.py install my-model owner/repository model-Q4_K_M.gguf mmproj-model.gguf
python local-ai/model_manager.py remove my-model
```

The last two are examples: choose the actual GGUF filenames from the repository listing. The install accepts only explicit GGUF files, no remote custom Python code or arbitrary paths. A vision-capable llama.cpp-compatible model needs a matching projector; arbitrary HF repositories or safetensors-only models will not work. The GUI currently identifies projectors by the mmproj filename convention. Restart/refresh the extension catalog after adding/removing models. Removal uses the running controller to avoid deleting active model files. To manually remove a partially downloaded or corrupt unregistered model, shut down the whole stack first, then delete only its folder from local-ai/models.

A model is registered in local-ai/models/<id>/model.json. The manifest contains id, label, repo, revision, weights, projector; the model and projector reside beside it. The default catalog remains visible as not installed if the model is removed. To change the shipped default, edit default-model.json, update the default ID in backend/local_ai.py and extension/src/shared/types.ts, then rebuild and qualify.

## Privacy requirements (not optional)

- Do not persist original pages, translated pages, base64 images, crops, inpainting/upscale intermediates, debug renders, prompts containing images, or website history.
- Original/translated image data is held in request/DOM memory only. The Python wrapper passes PIL objects directly to the pipeline and clears image caches after each page. All image file output and debug image file writing are disabled, including upstream path-based batch output.
- Extension upgrade deletes legacy mt_translated_cache keys without restoring them. Image fetches use no-store. No image history is written to chrome.storage.local, IndexedDB, downloads or Cache Storage. Volatile document caches are cleared on pagehide.
- Local requests force the loopback Python backend and loopback Rust service; user-configured cloud credentials/URLs are discarded in Local mode. The Rust worker takes inline image bytes only, with request logs disabled, no prompt-cache persistence, no network image URLs, no cloud fallback.
- Existing cloud mode intentionally sends images to the provider chosen by the user; the extension cannot control the provider's retention. Local-only mode is required for avoiding that exposure. Application privacy does not guarantee OS pagefile, crash dumps, browser-native cache, third-party webpage behavior, or physical-memory forensics.

## Codex acceptance checklist

Run `powershell -ExecutionPolicy Bypass -File local-ai/test.ps1 -PythonExe <your-python-path>` first. It executes Rust unit tests, Python compilation and mocked local integration/catalog tests, the TypeScript build and pure lifecycle/routing tests, then static no-temp-file/no-browser-persistence checks. These tests are supplied but **not run by the PR author**.

Then run setup, start the stack, close all existing pins and execute `local-ai/test.ps1 -Live` (or `python local-ai/smoke.py` with the backend's Python). The smoke creates a synthetic page in RAM and checks initial load, two warm vision requests and unload, without saving images. Record load/inference timings and verify translation quality, GPU residency and VRAM separately. A smoke success is not proof of manga translation quality.

1. Record exact engine build, Rust/toolchain version, GPU, CUDA driver, model revision, baseline GPU memory via nvidia-smi, cold/warm load time and per-page translation time. Do not invent benchmark numbers. Compare first page cold, subsequent pinned pages, SSD reload after unpin, and OS-cache warm load.
2. Build/load extension. Confirm default Local AI enabled for fresh installation, legacy cloud settings preserved, missing model shows actionable error, no cloud fallback and no API key required. Verify source Auto on Japanese/Korean/Chinese/English pages plus explicit selection and English output. Verify reasonable reading order, number of crops, no blank-page regression and translation fidelity. Use permitted fixtures or a locally generated page; do not add real manga pages to the repo or save copies.
3. Pin site A in window 1. Open another tab on site A in window 2. Navigate away/close the first tab; model stays in VRAM. Close/navigate the final site-A tab; if no running job or window/GUI pins, controller exits worker and releases its VRAM. Open similar but nonmatching domain, verify no keep. Check background/minimized tabs, same hostname different paths, multiple windows, browser restart and extension reload. Browser crash should release after TTL. Test explicit window pin and Release all session pins. Inspect chrome.storage.session and chrome.storage.local: site names may only exist temporarily in session memory, never in persistent keys.
4. Begin multi-crop page, close last matching tab while inference is active, confirm request/lease finishes without terminating worker prematurely; verify it unloads once last job ends. Test failing model load, cancellation, controller/worker crash, competing model choice, missing CUDA libraries, and GUI pin/release. If worker orphaned after forced supervisor termination on Windows, add a kill-on-close Windows Job Object before merging. The normal launcher terminates its process tree on exit.
5. GUI: install official default, list HF files, add a second compatible model (optional test), confirm dropdown refresh, reject model traversal/invalid files, remove inactive model, reject removing a loaded model, recover from incomplete download. The shipped catalog contains only the default.
6. Privacy: seed legacy extension cache entries with synthetic data; install/update and confirm deletion. With Process Monitor watch python.exe, manga-local.exe, llama-server.exe and browser storage directories for original/translated PNG/JPEG/WebP files, Base64 caches, temp writes or image-bearing logs through success, failure, batch, colored bubbles, outside-text and upscale. Assert API rejects path-based output. Check all additional model or utility code for image write paths. Disable/repair any path that persists images before merge. Check network: local translation should have no external inference traffic; downloads occur only at setup/model installation (existing detector download requirements apply). Verify no app-generated image writes; OS pagefile/native browsing cache are outside the application.
7. Test Windows PowerShell 5.1 GUI and startup with spaces in paths, CUDA device selection, correct pinned release flags and model/projector compatibility. Check the Rust worker readiness, bounded timeouts and kill behavior. Ensure the GUI remains usable during downloads. Capture only timings/errors/status, no screenshots or real page content in reports.
8. Test cloud regression using mocked provider requests (or an explicitly opted-in provider). Keep local default and BYO settings independent. Validate all existing API single/batch response formats. The previous source tree imported missing models.schemas from an ignored weights directory; this PR adds tracked api_schemas.py.

Fix compilation, test failures and model-specific prompt/context tuning in this PR. Generate and commit Cargo.lock after validating the dependency graph, record the actual qualification results and hashes, then mark ready for review. Merge only after the required checks pass and the repository owner authorizes it.
