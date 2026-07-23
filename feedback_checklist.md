# Reviewer feedback — addressed vs. un-addressed

Compared the annotated `xdqc_draft_7-10_SG.pdf` against the current LaTeX draft in `memq-dqc-paper/` (uncommitted working-tree edits on top of the commit *"prior to revisions from shobhit feedback"* — i.e. the diff **is** the revision set). No files were modified.

## ⚠️ Un-addressed / incomplete (the ones to act on)

| Pg | Comment | Status |
|----|---------|--------|
| 11 | **"Is there a reason behind this specific regime where ring is not the best topology?"** | **UN-ADDRESSED.** A new general-connectivity paragraph was added (results.tex L19), but it does **not** explain the specific ring→chain inversion at 60 qubits. The Fig. `epr_scaling` text still just says "*interestingly … at 60 qubits it outperforms the ring*" with no mechanism. → This is exactly what `reviewer_response_trends.md` provides. |
| 9  | Fig. 7 (Gantt) font size should match main text | **UN-ADDRESSED.** `figures/gantt_schedule.pdf` was not regenerated (untouched while other figures were re-exported on 07-13/07-16). |
| 1  | Discuss complete author list / acknowledgment before posting | **OPEN (process).** `\section*{Acknowledgment}` is still empty and the `\todo{add GitHub repository link}` placeholder remains in `main.tex`. |
| 12 | Fig. 11 (heatmap): font too small **and** color contrast too dark | **LIKELY ADDRESSED — verify visually.** `publication_relative_partitioning_performance_final.pdf` was regenerated (07-13), but the `\includegraphics` width was *reduced* to `0.9\textwidth`, which shrinks on-page text. Eyeball the fonts/contrast in the rebuilt PDF. |
| 10 | "Fig." abbreviation consistency | **MOSTLY DONE.** 15 uses of `Fig.~\ref` vs. 2 stragglers still written `Fig. \ref` (with a plain space). Trivial cleanup. |

## ✅ Addressed

| Pg | Comment | How it was handled |
|----|---------|--------------------|
| 11 | General trend: connectivity degree vs. EPR pairs | New paragraph, results.tex L19: connectivity lowers cost via routing distance, *but* degree alone isn't decisive (diameter, centrality, circuit structure, placement). |
| 8  | Scheduler discussed but absent from results | New subsection **"Dependence on Link-Arbitration Strategy"** + `scheduler_divergence.pdf` (FIFO vs SJF vs critical-path) + appendix fan-out circuit figure. |
| 11 | Fig. 10 confusing (same-size bars, unclear shading, dark colors); use side-by-side bars | Replaced with grouped paired-bar figures (`intra_qpu_connectivity_grouped_*`); caption now states paired bars = all-to-all (left) / nearest-neighbor (right). Adder example also updated 28→64 qubits. |
| 1  | (Abstract) "topology informed may be more suitable" | Abstract now reads "open-source, **topology-informed** framework". |
| 2  | Define EPR = Einstein–Podolsky–Rosen | background.tex: "entangled **Einstein–Podolsky–Rosen (EPR)** pairs". |
| 2  | "generates an execution schedule" more accurate | architecture.tex: "…and then **generates an execution schedule**". |
| 2  | Clarify what "co-design" means | introduction.tex L10: added definition (joint selection of compilation/scheduling + inter/intra-QPU topology + hardware, not one in isolation). |
| 2  | Shorten; drop "we aim to foster a … expertise" | introduction.tex L12: rewritten to "we aim to **enable collaborative research across the quantum networking, hardware, and algorithm design communities**". |
| 11 | "The cost in EPR pairs for" | Fig. intra-connectivity caption: "The **cost**, in EPR pairs…". |
| 11 | "dependence on intra-QPU connectivity" wording | Subsections renamed "**Dependence on** Inter-/Intra-QPU …" (was "Impact of"). |
| 12 | "layers spanning quantum networking, compilation and scheduling" | discussion.tex adopted this phrasing. |
| 12 | "users" more appropriate than "researchers" | discussion.tex: "allows **users** to contribute…". |
| 13 | "that minimize the EPR pair.." | future_work.tex: "enhanced algorithms **that minimize the EPR-pair consumption**". |
| 13 | Soften "makes clear the fact" (too strong) | future_work.tex: "our work **suggests that** the optimal strategy…". |
| 13 | Soften "lacks the robust software-hardware interface" | future_work.tex: "lacks a **standardized** software-hardware interface". |
| 1  | Strikeout: repeated in discussion — remove here | Duplicated "barrier to entry / expertise" text removed from both intro and discussion. |
| 1  | "This might not be relevant to current scope" | Out-of-scope sentence (datacenter CPUs/GPUs/FPGAs, error-correction) removed from introduction. |

## Bottom line
Most line-edit, wording, tone, and de-duplication comments are done, and the two biggest structural asks — a **scheduler result** and the **Fig. 10 redesign** — were completed. What remains open is: (1) the **scientific explanation of the ring-not-best regime** (the main one; drafted in `reviewer_response_trends.md`), (2) the **Gantt figure font**, (3) the **empty acknowledgment / GitHub link**, and (4) a **visual check of the heatmap** font/contrast plus 2 trivial "Fig." fixes.
