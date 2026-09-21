# Environment preparation contract

Environment preparation is an explicit, optional caller operation that turns one immutable source into one verified Axern Environment. It finishes before dataset resolution and is never an implicit action of `run`, a resolver, qualification, inference, or verification.

## V1 scope

`SeedBuildSpec v1` is closed to one digest-pinned `oci://` source, one mutable destination used only as the Kova publication target, one logical role, OCI output, and `linux/amd64`. The source URI digest must equal `source_digest`. The spec also fixes the preparation ID, recipe digest, Kova idempotency key, Axern namespace, working directory, and bounded non-sensitive labels. Unknown fields fail closed.

The canonical request digest commits the complete spec. Before calling Kova, the store atomically persists the spec, digest, stable idempotency key, and `build_submitting` state. Files are fsynced and renamed into place; the preparation lock protects only local transitions and is not held during remote waits.

## Recovery

The durable states are:

```text
new
  -> build_submitting
  -> build_submitted
  -> build_succeeded
  -> environment_creating
  -> environment_created
  -> ready
```

Terminal states are `failed` and `cancelled`; `ambiguous` records a mutation whose response was not trustworthy. A build-submission ambiguity may replay only the identical persisted request and idempotency key. Once a build ID is returned it is immediately persisted, and later observation failures resume that ID without another build submission. A terminal Kova failure never starts Environment creation.

An Environment-create ambiguity first lists by the Axrun preparation digest. Zero exact candidates permits creation; one candidate is accepted only when namespace, original immutable reference, resolved manifest digest, and platform evidence all match; multiple candidates or any mismatch is terminal. Axrun never reads Axern storage, private protocols, Node identity, or runtime identity.

## Receipts and episode boundary

A successful Kova result must contain exactly one output whose role target, platform, format, manifest digest, and credential-free immutable reference match the request. `SeedBuildReceipt` commits those facts and the public build identity. `EnvironmentPreparationReceipt` commits the exact requested reference, Axern-resolved digest, Environment ID, platform, and working directory. Both receipts are content-addressed.

Only a ready receipt can produce an `EnvironmentBinding`. The binding is then passed explicitly to an existing resolver. Preparation records and receipts are not CandidateBundles, do not alter the candidate digest, and cannot cross from inference to verification.

## Security boundary

Kova endpoint/token and Axern context remain caller process configuration. Registry credentials, HTTP headers and bodies, Docker configuration, kubeconfig, model credentials, Tunnel tokens, private IPs, and provider runtime identities are not fields in any preparation contract. Typed remote failures retain only operation, stable code, numeric status, retryability, ambiguity, and a bounded safe summary. Kova build error bodies are not persisted.

The optional Kova client is loaded only for preparation commands. A minimum Axrun installation can validate, resolve, run, inspect, and report episodes without importing Kova; invoking preparation without the `kova` extra returns a concise installation instruction.
