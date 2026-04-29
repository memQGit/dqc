# Scheduling Strategies

This repository currently exposes five concrete scheduling strategies:

- `fifo`
- `ilp`
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

The deterministic EPR duration used by `fifo` and `ilp` is

$$
t_{\mathrm{epr}} = \frac{1}{r},
$$

where $r$ is the configured entanglement generation rate.

The DES schedulers instead model repeated entanglement attempts with cycle time
$t_c$ and per-attempt success probability $p$.

## FIFO

File:
`src/memq_dqc/scheduler/fifo.py`

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

## ILP

File:
`src/memq_dqc/scheduler/ilp_scheduler.py`

Class:
`ILPScheduler`

Plain-language description:
This scheduler formulates scheduling as an integer linear program on a discrete
time grid. Every operation gets a binary start variable for each feasible start
step, and the solver chooses a globally optimal schedule subject to precedence
and resource constraints.

Objective:

$$
\min \left( W \, C_{\max} + \sum_i s_i \right),
$$

where $C_{\max}$ is the makespan and $W$ is a weight chosen large enough to
make makespan minimization dominate the secondary objective.

Core constraints:

$$
\sum_t x_{i,t} = 1
$$

$$
s_j \ge s_i + d_i \qquad \forall (i, j) \in E
$$

$$
\sum_{i \text{ active on } q \text{ at } t} x_{i,\cdot} \le 1
\qquad \forall q, t
$$

This strategy is deterministic and globally optimizing under its discrete-time
model. It is usually better than `fifo` on makespan, but it is more expensive
to run and still uses fixed EPR windows rather than stochastic attempts.

## DES Link FIFO

File:
`src/memq_dqc/scheduler/des_link_fifo.py`

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
`src/memq_dqc/scheduler/des_link_shortest_duration.py`

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
`src/memq_dqc/scheduler/des_link_critical_path.py`

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
