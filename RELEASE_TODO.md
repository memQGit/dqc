# Release TODO

Everything that must be resolved **before** xDQC is made public. Do not flip
repository visibility, publish to PyPI, or announce while any box is unchecked.

## Blocking

- [ ] **Decide whether to scrub git history, then act on the decision.**
      `benchmarking/`, `.cache/`, and the two paper-review docs are gone from
      `HEAD` but remain fully recoverable from history, and making the repo
      public publishes all history, not just the tip.
      - Only the paper-review docs are genuinely sensitive: they name a
        reviewer, cite an unpublished draft, and list un-addressed review
        comments. `benchmarking/` is transpiled circuits and topology JSON —
        not secret, but `.gitignore` says it is "kept local-only, not shipped
        to GitHub", so history contradicts stated intent. `.cache/` is a
        25 MB pickle, pure weight.
      - To scrub:
        `git filter-repo --invert-paths --path benchmarking --path .cache --path feedback_checklist.md --path reviewer_response_trends.md --force`
      - Cost: every SHA changes. All branches need force-pushing, merged PR
        commit links break, collaborators must re-clone, and `origin` is
        removed by the tool and must be re-added.
      - A pre-rewrite backup bundle of all refs exists in the session
        scratchpad; make a fresh `git bundle create <path> --all` first
        regardless.
- [ ] **Network topology schema reference.** The authoritative description of
      the network JSON format currently lives only inside
      `demo/networks.ipynb`. Extract it into a proper docs page
      (`docs/guide/networks.md` or equivalent) so it is findable without
      opening a notebook. Must cover: `processors` / `qubits` sections, the
      required `type` and `processorId` fields, that edges come **only** from
      `localConnections` / `remoteConnections` (top-level `connections` is
      ignored by `NetworkGraph`), and that routing through an intermediate QPU
      needs 2 remote pairs per link.
- [x] **`cost` now always reports measured e-bit usage.** `Partitioner.cost`
      extracts the distributed circuit on access, so the value no longer
      depends on whether the caller happened to touch `distributed_circuit`
      first. If extraction is impossible for a network, it falls back to the
      partition-time approximation and logs a warning.
- [ ] **Reconcile `remote_swap_ebit_cost` with the builder.** Surfaced by the
      fix above: for a routed swap across non-adjacent QPUs, the network's
      estimate prices 6 e-bits while the builder actually emits two adjacent
      remote swaps costing 4 (see
      `tests/builder/test_builder.py::test_cross_qpu_swap_routed_between_non_adjacent_qpus`).
      Partitioners optimise against the estimate, so an over-priced routed
      swap biases them away from routes that are in fact cheaper.
- [ ] **File an issue to restore strict type checking.** `pyrightconfig.json`
      is temporarily relaxed from `strict` to `basic` (see the comment in
      that file). Under `basic` there are still 103 real findings — 35 in
      `src/`, 68 in `tests/` — including a `list[CircuitQubit | None]`
      returned where `list[CircuitQubit]` is declared, in
      `src/xdqc/circuit/dag/remap.py`. Fix those, then restore `strict`,
      which additionally needs stubs or typed wrappers for networkx,
      matplotlib, and qiskit. Only after that is `py.typed` worth shipping —
      adding it now would advertise type quality that has not been verified.
- [ ] **Fix the broken `tests/fixtures/networks/50x2.json` fixture.** It has
      102 connected components across 104 qubits: all 100 computation qubits
      are isolated from every communication qubit, so no remote operation is
      possible and the distributed circuit cannot be extracted at all.
      `test_partitioner_large_circuit` only passes because `cost` falls back
      to the approximation.

## Documentation

- [ ] Hardware and settings guide (`settings.toml`, modalities, entanglement
      profiles, `SchedulerHardwareProfile` overrides).
- [ ] Move root-level `scheduling.md` into `docs/guide/`.
- [x] Docs site renders the notebooks via `mkdocs-jupyter`; all image
      references verified to resolve.

## Packaging

- [x] Claim the `xdqc` name on PyPI and add a trusted-publishing workflow.
      Pending publisher registered (owner `memQGit`, repo `xdqc`, workflow
      `publish.yml`, environment `pypi`) and `.github/workflows/publish.yml`
      is committed.
- [ ] **Finish trusted publishing on the GitHub / RTD side.** The local half
      is done; these are all owner actions in web UIs:
      - [ ] Create the `pypi` environment under Settings -> Environments. The
            name must match `environment:` in `publish.yml` and the value
            given to the PyPI pending publisher, or the OIDC claim is
            rejected at publish time.
      - [ ] Flip repository visibility to public. **Blocked on the history
            scrub above** — `benchmarking/`, `.cache/`,
            `feedback_checklist.md`, and `reviewer_response_trends.md` are
            gone from `HEAD` but still recoverable from history.
      - [ ] Import the repo on Read the Docs (needs public visibility; the
            Community tier does not accept private repos). Confirm the
            project slug is exactly `xdqc`, otherwise the README badge and
            the `xdqc.readthedocs.io` link both break.
      - [ ] Dry-run the release against TestPyPI before the real one. A
            version number can never be reused on PyPI, so a bad `0.1.0` is
            permanent.
- [ ] `CITATION.cff` + Zenodo DOI (coordinate with the paper).
- [ ] Tag `v0.1.0` and write the first real `CHANGELOG.md` entry.
- [ ] `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue/PR templates.

## Cleanup

- [ ] Remove unreferenced `demo/outputs/schedule_gantt_font*.png` (~1.5 MB of
      leftovers from font experiments).
- [ ] Decide whether generated `demo/outputs/` artifacts stay tracked
      long-term; re-running notebooks accumulates history.
