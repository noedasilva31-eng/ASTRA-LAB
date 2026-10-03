
## V1b interruption test: normalized -> publication

Archive and normalize one live read-only RPC capture, then stop deliberately before publication:

```bat
py -m astra --db var/publish-recovery.sqlite solana-rpc --stop-before-publish
```

After restarting, disconnect the network and run recovery twice. Publication is keyed by `capture_id`, so both normalization and publication are idempotent:

```bat
py -m astra --db var/publish-recovery.sqlite recover
py -m astra --db var/publish-recovery.sqlite recover
py -m astra --db var/publish-recovery.sqlite replay-rpc 1
```

## V1b source-identity conflict test

Create one live read-only RPC capture while online:

```bat
py -m astra --db var/conflict-test.sqlite solana-rpc
```

Then disconnect the network. `conflict-rpc` creates a separate test copy, changes only
`lastValidBlockHeight`, preserves the source identity (`slot:blockhash`), and never edits
the original raw capture:

```bat
py -m astra --db var/conflict-test.sqlite conflict-rpc 1
py -m astra --db var/conflict-test.sqlite recover
py -m astra --db var/conflict-test.sqlite health
py -m astra --db var/conflict-test.sqlite replay-rpc 1
```

Expected: capture 2 is `quarantined` with reason `source ID conflict`; there is still one
accepted/publication, no pending/unpublished item, no hash errors, and capture 1 replays
with `match:true`. A quarantine intentionally makes the aggregate `healthy` flag false in
this reference journal, because health treats any quarantine as an operator-visible alert.
