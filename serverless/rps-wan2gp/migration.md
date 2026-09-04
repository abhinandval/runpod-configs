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

- Untracked `AGENTS.md` — project-specific automation and generation guidance;
  intentionally excluded from the public monorepo because it contains internal
  guidance.
- Untracked `hello-world.mp4` — user media; intentionally excluded from the
  public monorepo pending content and licensing review.
- Untracked `lightning_octopus.mp4` — user media; intentionally excluded from
  the public monorepo pending content and licensing review.
- Two linked worktrees are present under `.worktrees/`:
  - `feat/jolt-wan2gp-design` at `f554540`.
  - `fix/report-wangp-errors` at `e741e9b`.
- `.worktrees/` is ignored and is not part of the migration snapshot. The linked worktrees and their branch histories were relocated outside the original checkout and monorepo to a temporary backup, and require separate reconciliation if their work is intended for the monorepo.
- Before migration, the local linked worktrees were relocated outside the
  monorepo to a temporary backup, preserving the branch names and commit IDs
  listed above. The backup location is intentionally not documented here as a
  personal absolute filesystem path; it is local-only and is not part of the
  public migration.

## Public-repository audit

- No credential-bearing filenames were found.
- A repository-wide scan of the visible source files found no API keys, tokens,
  passwords, authorization headers, or private-key material.
- The `.playwright-mcp/` directory contained generated browser logs, page state,
  and a screenshot. It was removed as generated metadata that could capture
  private or session-specific information, and `.gitignore` now excludes it.
- `AGENTS.md` and both MP4 files were intentionally excluded from the public
  monorepo. `AGENTS.md` was excluded because it contains internal automation
  guidance; the MP4 files were excluded because their content and licensing
  were not approved for public redistribution. All three remain part of the
  original source checkout's untracked worktree state described above.

## Migration caveats

1. The source checkout is behind its remote. This migration record describes
   the checked-out commit, not the latest remote implementation.
2. The source remote's later fixes and feature branches are not implicitly
   merged into this snapshot.
3. The monorepo migration must not copy `.git/`; the original repository's
   history remains available from the original remote.
4. The source checkout contained large media files, but both MP4 files were
   excluded from the public snapshot pending content and licensing approval.
   Consider Git LFS or a release/object-storage policy if they are later
   approved for publication.
5. Re-run secret scanning on the final monorepo, including all sibling
   projects, immediately before the public push.
