# Greenfield workspace archive arm64 E2E

Date: 2026-09-19

This acceptance used Axrun `756ac228e5132b9a46c3706bc2ac5a992e1cfc91`, Axern `606cf92195e6ccbbbeb6b4cc40fb1c6a131db987`, and released `axern-sdk==0.9.1` against the source-managed arm64 Compose cluster. No Axern source or private Proto was used by Axrun.

## Immutable runtime inputs

| Role | Local image ID | Axern canonical digest | Environment |
| --- | --- | --- | --- |
| inference | `sha256:a3264514ce8d73bd3d6ab10563ab3876c87015636a8241266980def597f77f99` | `index.docker.io/library/axrun-greenfield-inference@sha256:181377f989b5bc02f510616277f5385f0216c8503c5963fe2126cc6beba31fbf` | `env-83701e5c-4c76-4093-95f6-56b8339182f2` |
| verification | `sha256:069edefa745a39505103bdd0fe2374858c81e3b948976b6671bdd51453b41ef6` | `index.docker.io/library/axrun-greenfield-verification@sha256:e1f5367bcd92eeac902ed946777c530bcc3c4bd4bc34d9fa444abe4180ee6566` | `env-dc1e9501-1c6e-4e4e-9b99-0163b8af5bdf` |
| Claude Code rootfs | `sha256:72a250f33a1b1a2d711b4ac263692cca9030cb4c1a3a8b329866824464253524` | `index.docker.io/library/axrun-claude-code-rootfs@sha256:66688f9bef794b63a3104588a19b3e6c09091b6729dc4082cd1bf0d0664f2633` | readonly inference ImageMount |

Both task images reported `linux/arm64`; qualification observed `aarch64`, Python `3.11.16`, `/workspace`, no Git requirement, and an empty workspace. The inference and verification bindings intentionally use different images and Environments. amd64 remains the canonical benchmark platform; this record validates local source-cluster development on arm64.

## Deterministic paths

| Episode | Qualification Runs / Allocations | Inference Run / Allocation | Verification Run / Allocation | CandidateBundle | VerificationResult | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| `greenfield-gold-arm64-20260919-03` | `run-06373bd5-cf05-4b8d-b0f3-16a8f26a920f` / `alloc-ecedc1d8-0286-47b9-ac51-47032db6bbba`; `run-03234fb2-b615-4ec3-84a7-c20b83c1cbef` / `alloc-f57fd385-0a62-46d4-bbc0-4dbef6728d25` | `run-d6411c22-4498-4546-b548-8e54e1931675` / `alloc-80631f49-f8eb-4592-aacf-519fa9c007ce` | `run-262704df-ee83-4f36-9de6-31404d9a64ee` / `alloc-036e3f9b-2d2e-45e6-8db5-a7795651e3b2` | `7196c3be28d79ce33cf27a363a738d84a52d5664264476937dd2e20af83c764a` | `ba90f126bd907e7d450830b4d9499bbf475b21c9989255a4101a7f24c7f601b6` | passed / 1.0 |
| `greenfield-empty-arm64-20260919-01` | `run-73a26973-534b-4716-b0e2-a4bb85046ce7` / `alloc-54a0080c-b82d-44dc-ab16-367fb08b3b0f`; `run-54bb2a12-1e7f-4e00-b9a9-798933e83d5a` / `alloc-372b3cb1-e426-41c9-bfcd-44e806f7360a` | `run-5d9e6af9-417e-49bc-9ca7-b18a1ce359ae` / `alloc-42e08fea-f4a1-48ce-b0d1-838bf5af60ee` | `run-f0a7d54f-4136-4b6f-bbde-47bc7206fe78` / `alloc-b94e0fc4-31d1-469e-a7ca-485286676374` | `0091a0deb23fb1c709a4e1b8983234ebe15907519489295fa39c9ccc90fdb9f9` | `1e4dd0681e44687187fd68b1dbf81479ac058e8914baefc2ef09f103d42a41d1` | failed / 0.0 / `greenfield_contract_failed` |
| `greenfield-known-bad-arm64-20260919-01` | `run-18bfe60b-61dc-40a4-9fe0-07bc0c2406d4` / `alloc-af3247eb-b173-43f3-9b96-c02ef1cd8cba`; `run-12868827-8075-4811-a13c-de80192e95bd` / `alloc-ab23b192-1cd3-4ed6-8e6b-aee0ffe78bed` | `run-82c7cd69-62e4-4625-b67c-be97b0b7eb28` / `alloc-afd27426-e5e0-43c2-8acc-17d7c820820d` | `run-f5e2edd3-0d2a-4cb3-8218-2e3f5c7de759` / `alloc-695dba1c-fcb8-49f4-a085-398ce079edb8` | `736492c1c9a16aeda1d673962ac3a50e6a2ba954cf141deb64a9d1a6e4c1eb4b` | `381f9022860c8ae1092cce196a920e82c24e4d5b4e68236e85d010cf9cc649a7` | failed / 0.0 / `greenfield_contract_failed` |

All three paths used `workspace-archive@1`, independently downloaded and SHA-256-verified sealed output, a content-addressed CandidateBundle, and a fresh deny-all verification Run. The valid failed verdicts had verifier exit code zero and were not infrastructure failures.

## Real Claude path

Episode `greenfield-claude-arm64-20260919-01` used provider-neutral runtime configuration: base URL `https://api.deepseek.com/anthropic`, model `deepseek-flash`, Opus and Sonnet aliases `deepseek-flash[1m]`, Haiku and subagent aliases `deepseek-flash`, effort `max`, auto-compact window `786432`, and WebFetch/WebSearch disabled. The credential variable name was `DEEPSEEK_API_KEY`; its value was never recorded.

- inference qualification: `run-c4130a12-11b1-429f-9678-fb63e507bc10` / `alloc-ad00633c-a25a-4961-b6e0-43d84b0c714d`
- verification qualification: `run-6192a5a5-d669-48ab-98ef-ecb192953a16` / `alloc-a6bd0f72-a11d-484f-9073-efe2edf83e0d`
- inference: `run-3c29de4a-035e-435f-a72d-3d371e35b394` / `alloc-508508ac-846a-43a2-955e-3bf812465e72`
- verification: `run-c275b404-a8ba-4c40-aa17-12e31e50b17b` / `alloc-058f5174-c04d-4af4-8cca-9d3fb5cbfa9c`
- CandidateBundle: `9e800a91fc41a53cbb0df7164b7ab86dc82f57fad0eef1e53b86b60b7843c637`
- TrajectoryBundle: `2291bc6317d7419661e2085057316a8d87cca7272be1d4ec85fa5325831da62b` with 23 canonical events
- VerificationResult: `91631a32b94db7b50cbd5c235c22c3eb019c87d613a58a2877547c0b6cfab528`
- verdict: valid failed, score 0.0, diagnostic `greenfield_contract_failed`; the implementation missed the no-argument and empty-name edge cases

The four sealed inference outputs were independently downloaded and verified:

| Output | Bytes | SHA-256 |
| --- | ---: | --- |
| `workspace.tar` | 10,240 | `4886a99cfc9fd1601c03f43edc2f96ed98ec9d16950737c6ed207a7e189e5b68` |
| `trajectory.jsonl` | 11,956 | `a8debe4169072586d32eb43a1366f9aa4d4cbb2fbc9c61e13df09857298a2d65` |
| `harness.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `usage.json` | 144 | `0aeb4546a7cd620a0feb05b4c95607954ab0b14ecef65611f211611c92453090` |

`verify-record` returned `integrity_verified=true`. A fixed-string scan of the caller state directory for the live credential value returned zero matches. After completion the source node reported no remaining Claude/Axrun process or `/__claude_code` mount, confirming connector, TunnelSession, ModelProxy, process, and mount cleanup.

## Reproduction

```bash
uv run axrun resolve-greenfield fixtures/synthetic/greenfield-task-v1/row.json \
  --episode-id NEW_EPISODE_ID --harness claude-code \
  --inference-image "$INFERENCE_DIGEST" --verification-image "$VERIFICATION_DIGEST" \
  --task-platform linux/arm64 --claude-mount-image "$CLAUDE_ROOTFS_DIGEST" \
  --model deepseek-flash --claude-default-opus-model 'deepseek-flash[1m]' \
  --claude-default-sonnet-model 'deepseek-flash[1m]' \
  --claude-default-haiku-model deepseek-flash --claude-subagent-model deepseek-flash \
  --claude-effort-level max --claude-auto-compact-window 786432 \
  --inference-environment "$INFERENCE_ENVIRONMENT_ID" \
  --verification-environment "$VERIFICATION_ENVIRONMENT_ID" \
  --output /tmp/greenfield-claude.json

uv run axrun --state-dir .axrun-greenfield \
  --context-file "$HOME/.config/axern/config.json" --context compose \
  --model-upstream-url https://api.deepseek.com/anthropic \
  --model-credential-env DEEPSEEK_API_KEY --model-response-timeout-seconds 600 \
  run /tmp/greenfield-claude.json
```
