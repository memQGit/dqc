# Scheduling Strategies

This repository currently exposes four concrete scheduling strategies:

- `fifo`
- `des_link_fifo`
- `des_link_shortest_duration`
- `des_link_critical_path`

## Shared Timing Model

All schedulers use the same deterministic gate durations from the scheduler
timing model:

$$
d_i =
\begin{cases}
t_{1q}, & \text{if } i \text{ is a local 1Q gate} \\
t_{2q}, & \text{if } i \text{ is a local 2Q gate} \\
t_{\mathrm{meas}}, & \text{if } i \text{ is a measurement} \\
t_{2q} + t_{\mathrm{meas}} + t_{1q}, &
\text{if } i \text{ is a remote gate} \\
t_{2q} + 2 t_{1q} + t_{\mathrm{meas}}, &
\text{if } i \text{ is an } \mathrm{rswap}
\end{cases}
$$

The deterministic EPR duration used by `fifo` is

$$
t_{\mathrm{epr}} = \frac{1}{r},
$$

where $r$ is the configured entanglement generation rate.

The DES schedulers instead model repeated entanglement attempts with cycle time
$t_c$ and per-attempt success probability $p$.

### Configuring the parameters

$t_{1q}$, $t_{2q}$, $t_{\mathrm{meas}}$, $r$, and the EPR lifetime are the
primitive parameters; every duration above is derived from them. They default
to the modality and entanglement profile selected in
`src/xdqc/settings.toml`, and each can be overridden per compile or per
scheduler run on `SchedulerHardwareProfile`:

```python
from xdqc import SchedulerHardwareProfile

profile = SchedulerHardwareProfile.sr_trapped_ion(
    two_qubit_gate_time=120.0,
    epr_lifetime=80.0,
)
```

Pass it as `Scheduler(source, profile=profile)`, or as
`SchedulingCompileOptions(hardware_profile=profile)` for
`compile_scheduling_instance`. The derived durations recompute from whatever
values are in effect, so they always stay consistent with the primitives.
$t_c$ (`des_entanglement_time_step`) remains global to `settings.toml`.

## FIFO

File:
`src/xdqc/scheduler/fifo.py`

Class:
`FIFOScheduler`

Plain-language description:
This is a greedy baseline scheduler. It walks the DAG layer by layer and
schedules each operation at the earliest time when all of its qubits are free.
Remote operations receive just-in-time EPR events of fixed duration, and the
remote gate starts immediately after those EPR windows finish.

Core rule:

$$
s_i = \max_{q \in Q_i} a_q,
$$

where $Q_i$ is the set of qubits touched by operation $i$ and $a_q$ is the
current availability time of qubit $q$.

For a remote operation, the start time is also constrained by the required EPR
windows:

$$
s_i = \max \left(
\max_{q \in Q_i^{\mathrm{data}}} a_q,
\max_{e \in E_i} (a_e + t_{\mathrm{epr}})
\right).
$$

This strategy is fast and deterministic, but it is only locally greedy. It does
not search globally for the best schedule, and it does not model stochastic EPR
retries or expiration.

## DES Link FIFO

File:
`src/xdqc/scheduler/des_link_fifo.py`

Class:
`DESLinkFIFOScheduler`

Plain-language description:
This scheduler runs a discrete-event simulation in which remote operations
request EPR pairs on their communication links. Each link can host at most one
active entanglement process at a time. If several operations want the same
link, the oldest blocked request wins when that link becomes free.

Entanglement attempt model:

$$
\Pr[T = k t_c] = (1 - p)^{k-1} p,
\qquad k = 1, 2, 3, \ldots
$$

Link arbitration rule:

$$
\pi_{\mathrm{fifo}}(\ell, t) =
\arg\min_{o \in R_{\ell}(t)} \mathrm{enqueue\_order}(o),
$$

where $R_{\ell}(t)$ is the set of requests waiting for link $\ell$ at time
$t$.

This strategy keeps the physical DES model of retries, waiting, expiration, and
regeneration, but it resolves link contention using pure FIFO order.

## DES Link Shortest Duration

File:
`src/xdqc/scheduler/des_link_shortest_duration.py`

Class:
`DESLinkShortestDurationScheduler`

Plain-language description:
This strategy uses the same DES engine as `des_link_fifo`, but changes the
link-arbitration rule. When several blocked remote operations want the same
link, it prefers the request whose remote operation has the smallest
deterministic duration.

Link arbitration rule:

$$
\pi_{\mathrm{short}}(\ell, t) =
\arg\min_{o \in R_{\ell}(t)} d_o.
$$

Tie break:

$$
d_o = d_{o'} \Rightarrow
\text{pick the smaller enqueue order.}
$$

This strategy is useful when the goal is to clear short remote work quickly and
reduce head-of-line blocking on busy links.

## DES Link Critical Path

File:
`src/xdqc/scheduler/des_link_critical_path.py`

Class:
`DESLinkCriticalPathScheduler`

Plain-language description:
This strategy also uses the same DES engine, but it prioritizes requests that
sit on a larger remaining downstream critical path. It is a heuristic for
improving overall makespan when link contention would otherwise delay the most
important remote work.

Remaining-path score:

$$
c_i = d_i + \max_{(i, j) \in E} c_j,
$$

with

$$
c_i = d_i
\qquad \text{for sink nodes.}
$$

Link arbitration rule:

$$
\pi_{\mathrm{cp}}(\ell, t) =
\arg\max_{o \in R_{\ell}(t)} c_o.
$$

Tie break:

$$
c_o = c_{o'} \Rightarrow
\text{pick the smaller enqueue order.}
$$

This strategy keeps the stochastic DES model while biasing the scheduler toward
requests whose delay is most likely to extend the final makespan.
