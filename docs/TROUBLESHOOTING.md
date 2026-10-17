# Troubleshooting

### No “AI诊断” in the right sidebar

Check that the generated loader is enabled in Tampermonkey. Chrome may require
“Allow access to file URLs” and “Allow user scripts.” Refresh the Bilibili
video page after updating the loader; a previously opened page keeps its
already-injected JavaScript. The UI only appears on supported pages with
Bilibili's expected right-side danmaku list DOM. The diagnostics Tampermonkey
menu command is an alternative if the sidebar header is missing.

### The old floating “AI弹幕” button is still visible

The current version has no such video-overlay button. Check for an older,
separately installed userscript and disable it. Update/reimport the generated
local loader, then reload the video page. Tampermonkey may cache `@require`
dependencies across updates.

### “Backend offline” or local API cannot connect

Start `python browser_filter/backend.py`. Verify the port is not already
used by another backend, visit `http://127.0.0.1:39683/health`, and wait
for `status=ready`. First model load can be slow. To use a different port,
provide the same port to both the userscript builder and backend using their
`--port` options, then reimport the generated loader.

### 401 Unauthorized / script keeps reconnecting

The local userscript and server must use the same token file. Re-run
`python browser_filter/build_userscript.py` in the same repository,
update the local loader in Tampermonkey, and reload the video. Do not paste
a token into a public issue.

### Model cannot be found / load failure

Run `python scripts/download_model.py`, then
`python scripts/extract_text_only.py`. If you already have a compatible
text-only model, set `AI_DANMAKU_MODEL_DIR` to its absolute directory.
No model weights are stored in the Git repository. If an upstream Hugging Face
repository changes checkpoint names, review the upstream model layout.

### Comments are visible briefly before being hidden

This is intentional. Unclassified danmaku remain visible until a decision
comes back. The optional prefetch reduces but does not guarantee zero flashes.

### Wrong comments filtered / false positives

Start with the balanced (F1-oriented) preset, turn off unwanted categories,
adjust per-category sensitivity, or put exact phrases on the always-allow list.
Use the sidebar diagnostics to see actual decisions and their causes.

### Installing as a Windows background task

After manually verifying the backend, run the optional
`scripts/install_windows_task.ps1` in PowerShell to launch at login.
Use `scripts/uninstall_windows_task.ps1` to remove this repository's
task. Neither operation is required for manual use.
