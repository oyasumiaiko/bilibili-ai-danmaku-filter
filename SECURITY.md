# Security policy

## Reporting a vulnerability

Please report credential leaks, arbitrary local API access, unsafe HTML injection,
or file-path handling bugs privately to the repository owner through GitHub's
private vulnerability reporting feature (Security → Advisories), where available.
Do not publish credential material in an issue or pull request.

## Security boundaries

- The Python server binds only to 127.0.0.1 by default and checks the HTTP Host.
- State-changing and classification API calls require a randomly generated local
  token; the health endpoint has no token by design.
- The *generated* userscript includes that token. Anyone with read access to the
  script can read the token, so do not share it publicly.
- The token file, generated scripts, caches, model weights, HAR, and browser
  profiles are gitignored. Verify staged files before each push.
- The source template uses textContent for untrusted danmaku strings in the
  diagnostics UI, not innerHTML string interpolation of third-party text.
- Do not expose or reverse-proxy the local HTTP service to the public network.
- This is a personal/local prototype, not a hardened multi-user production API.

## Supported versions

Security fixes will target the newest repository main branch. Prior snapshots
are not maintained as independent supported releases.
