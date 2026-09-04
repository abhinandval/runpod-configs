# Contributing

This is a public repository containing RunPod configuration and local inference projects. Keep changes reviewable, reproducible, and safe to run without access to anyone's accounts.

## Before opening a change

- Read the project README and any project-local `AGENTS.md` before editing that project.
- Run `mise run check` from the repository root.
- Do not run cloud operations, deploy endpoints, submit paid jobs, or access private model/storage resources as part of normal validation.
- Inspect the final diff and confirm that it contains no credentials, tokens, personal data, private URLs, local paths, generated artifacts, model files, or unrelated changes.

## Commits

Use Conventional Commits for commit messages:

```text
<type>(<scope>): <imperative summary>
```

Examples: `feat(qwen38): add guarded serverless worker`, `fix(wan2gp): correct image defaults`, and `docs: clarify local validation`.

Use a small, atomic commit for one coherent change. Keep implementation, tests, documentation, and required configuration together when they describe the same change. Split unrelated cleanup, formatting, migrations, and features into separate commits. Do not mix a repository migration with new behavior unless the behavior is required for the migration.

Allowed types include `feat`, `fix`, `docs`, `test`, `build`, `ci`, `refactor`, `perf`, and `chore`. Use a scope when it makes the affected project obvious. Keep the subject concise, imperative, and without a trailing period. Use the body when context or operational risk needs explanation; include breaking changes with a `BREAKING CHANGE:` footer.

## Public-repository safety

- Never commit API keys, access tokens, SSH keys, cloud credentials, `.env` files, cookies, passwords, private endpoints, or personal machine details.
- Use placeholders such as `REPLACE_ME` in examples and document required environment variables without supplying values.
- Treat Dockerfiles, shell scripts, CI files, and deployment configuration as executable code: quote variables, validate inputs, fail safely, and avoid destructive defaults.
- Keep paid or externally mutating commands behind explicit confirmation flags. Local checks must remain credential-free and offline where practical.
- Pin important tool, image, and model revisions when reproducibility matters, and document any unavoidable floating dependency.
- Do not add downloaded models, build outputs, logs, caches, videos, or other large generated files without an explicit reason and review.

## Pull requests

Describe what changed, why it changed, and how it was validated. Call out anything not tested locally, especially GPU, Docker runtime, RunPod, network-volume, or billing behavior. Keep the PR focused and make rollback or operational impact clear.
