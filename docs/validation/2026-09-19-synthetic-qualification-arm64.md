# Synthetic Claude qualification on arm64

This record validates the model-free qualification gate against the running arm64 Axern source
Compose cluster. It did not read a model credential, create a Tunnel, or call an upstream model.

- Axrun commit before this record: `dbb96d736c3ffe404b7dc7a9aadde7c26426dde4`
- Axern commit: `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`
- Released SDK: `axern-sdk==0.9.1`
- Platform: `linux/arm64` (`aarch64` in the Allocation)
- Environment: `env-e01cb28a-ec64-46c8-9f90-eb7f1ed1656a`
- Task image: `index.docker.io/library/axrun-synthetic-code-task@sha256:207342f294efcbb882aef9f401dc84120f15ecbfcd8c1c429e3821d3df1324c7`
- Claude rootfs: `index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633`
- Local Claude image ID: `sha256:72a250f33a1b1a2d711b4ac263692cca9030cb4c1a3a8b329866824464253524`
- Qualification Run: `run-9b52ad2e-4ee8-45de-bf99-fde32e3b9ace`
- Qualification Allocation: `alloc-adc50209-3187-4308-a9bd-b27544e729af`
- Qualification sealed output SHA-256: `ce08b6c336e26d7de986273b52b8ed149b4f56a1ed17d137947496d951d55aed`
- Qualification evidence digest: `9fe52122386ba5887b524720377937a6be1bf468d0c53ed5bdf405290d152a49`

The sealed checks reported Git `2.39.5`, Python `3.11.16`, Claude Code `2.1.205`, Node.js
`v22.23.2`, clean base commit `69b31ae17c45d731fd5b6fa43660c05aea4a9027`, and a read-only
`/__claude_code` mount. Running the same `qualify` command again returned the bound evidence and
the same Run/Allocation instead of creating a duplicate Run.

Reproduction (no model environment variable is required):

```bash
uv run axrun resolve-synthetic fixtures/synthetic/code-task-v1/row.json \
  --episode-id synthetic-qualification-20260919-01 \
  --harness claude-code \
  --claude-mount-image 'index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633' \
  --model qualification-no-model-call \
  --inference-environment env-e01cb28a-ec64-46c8-9f90-eb7f1ed1656a \
  --verification-environment env-e01cb28a-ec64-46c8-9f90-eb7f1ed1656a \
  --output /tmp/axrun-synthetic-qualification-20260919-01.json

uv run axrun --state-dir .axrun \
  --context-file "$HOME/.config/axern/config.json" --context compose \
  qualify /tmp/axrun-synthetic-qualification-20260919-01.json
```
