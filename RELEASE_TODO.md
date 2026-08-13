# Release TODO

Everything that must be resolved **before** xDQC is made public. Do not flip
repository visibility, publish to PyPI, or announce while any box is unchecked.

## Blocking

- [ ] **Scrub git history.** `benchmarking/`, `.cache/`, and the two removed
      paper-review docs are gone from `HEAD` but remain recoverable from
      history. Run:
      `git filter-repo --invert-paths --path benchmarking --path .cache --path feedback_checklist.md --path reviewer_response_trends.md --force`
      Rewrites every SHA: all branches need force-pushing and `origin` must be
      re-added afterwards. Backup bundle is in the session scratchpad.
- [ ] **Network topology schema reference.** The authoritative description of
      the network JSON format currently lives only inside
      `demo/networks.ipynb`. Extract it into a proper docs page
      (`docs/guide/networks.md` or equivalent) so it is findable without
      opening a notebook. Must cover: `processors` / `qubits` sections, the
      required `type` and `processorId` fields, that edges come **only** from
      `localConnections` / `remoteConnections` (top-level `connections` is
      ignored by `NetworkGraph`), and that routing through an intermediate QPU
      needs 2 remote pairs per link.
- [ ] **Decide the `cost` semantics.** `Compiler.cost` returns a partition-time
      *estimate* until the distributed circuit is extracted, then silently
      becomes the *exact* measured value (e.g. 38 -> 36 on the chain, 80 -> 90
      on the ring). For a benchmarking library, one property returning two
      different quantities is a footgun. Either separate them
      (`estimated_cost` / `exact_cost`), or always extract eagerly.

## Documentation

- [ ] Hardware and settings guide (`settings.toml`, modalities, entanglement
      profiles, `SchedulerHardwareProfile` overrides).
- [ ] Move root-level `scheduling.md` into `docs/guide/`.
- [ ] Confirm the docs site renders the notebooks correctly once
      `mkdocs-jupyter` is wired up.

## Packaging

- [ ] Claim the `xdqc` name on PyPI and add a trusted-publishing workflow.
- [ ] `CITATION.cff` + Zenodo DOI (coordinate with the paper).
- [ ] Tag `v0.1.0` and write the first real `CHANGELOG.md` entry.
- [ ] `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue/PR templates.

## Cleanup

- [ ] Remove unreferenced `demo/outputs/schedule_gantt_font*.png` (~1.5 MB of
      leftovers from font experiments).
- [ ] Decide whether generated `demo/outputs/` artifacts stay tracked
      long-term; re-running notebooks accumulates history.
