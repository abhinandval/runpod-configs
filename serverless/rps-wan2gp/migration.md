# WAN2GP migration record

This file records the state of the existing `rps-wan2gp` repository immediately
before it is migrated into the public `runpod-configs` monorepo.

## Repository identity

- Original remote: `git@github.com:abhinandval/rps-wan2gp.git`
- Current branch: `main`
- Current commit: `908c71d114ac3f728130c4a4d0de66534e6e7849` (`chore: initialize project`)
- Remote-tracking branch: `origin/main` at `a7fc448` (`Merge pull request #4 from abhinandval/fix/report-wangp-errors`)
- Branch status: local `main` is 9 commits behind `origin/main`; it has no local commits ahead of the remote.
- Migration intent: preserve this repository's current working-tree snapshot as a directory in `runpod-configs`; its Git history is intentionally not carried into the monorepo.

## Open worktree state

The source repository was not clean at migration time:

- Untracked `AGENTS.md` — project-specific automation and generation guidance.
- Untracked `hello-world.mp4` — user media; preserved.
- Untracked `lightning_octopus.mp4` — user media; preserved.
- Two linked worktrees are present under `.worktrees/`:
  - `feat/jolt-wan2gp-design` at `f554540`.
  - `fix/report-wangp-errors` at `e741e9b`.
- `.worktrees/` is ignored and is not part of the migration snapshot. The linked worktrees and their branch histories remain in the original repository checkout and require separate reconciliation if their work is intended for the monorepo.

## Public-repository audit

- No credential-bearing filenames were found.
- A repository-wide scan of the visible source files found no API keys, tokens,
  passwords, authorization headers, or private-key material.
- The `.playwright-mcp/` directory contained generated browser logs, page state,
  and a screenshot. It was removed as generated metadata that could capture
  private or session-specific information, and `.gitignore` now excludes it.
- The two MP4 files were reviewed as user media by filename and size and were
  preserved. They are not automatically classified as secrets; review their
  content and licensing before publishing if needed.
- `AGENTS.md` was preserved because it is intentional project guidance rather
  than generated metadata. Review whether these internal automation rules
  belong in a public monorepo before publishing.

## Migration caveats

1. The source checkout is behind its remote. This migration record describes
   the checked-out commit, not the latest remote implementation.
2. The source remote's later fixes and feature branches are not implicitly
   merged into this snapshot.
3. The monorepo migration must not copy `.git/`; the original repository's
   history remains available from the original remote.
4. Large media files increase clone and checkout cost. Preserve them for now,
   but consider Git LFS or a release/object-storage policy before publishing.
5. Re-run secret scanning on the final monorepo, including all sibling
   projects, immediately before the public push.
