# Cluster Specification

A cluster is a **business ecosystem containing related plugins**. It is the
second of the four levels: below CORE, above PLUGIN.

Authority: `contract.md` §6, §7, §19.

## The 8 initial clusters

Seeded by `atlas_core/domain/clusters.py::INITIAL_CLUSTERS`, registered at boot
by `Kernel._seed_clusters()`. The map is **extensible** — a new cluster uses
exactly the same `register()` path as the seed.

| cluster_id | Name | Scope |
|---|---|---|
| `cluster.workforce_and_time` | Workforce & Time | attendance, leave, permission, overtime |
| `cluster.workplace_and_operations` | Workplace & Operations | workplace, field and workforce operations |
| `cluster.mobility_and_fleet` | Mobility & Fleet | fleet operations, mobility integrations |
| `cluster.employee_finance` | Employee Finance | employee finance, payroll |
| `cluster.employee_lifecycle_and_development` | Employee Lifecycle & Development | recruitment, onboarding, development, offboarding |
| `cluster.employee_services_and_rights` | Employee Services & Rights | HR service desk, employee rights, confidential cases |
| `cluster.information_and_documents` | Information & Documents | report studio, document exchange, cloud integrations |
| `cluster.governance_and_management` | Governance & Management | governance, administrative decisions, policy, management views |

The ids are dotted strings; the prefix is `cluster.`. A plugin's `cluster_id`
must match one of the registered ids (or a cluster registered later).

## Cluster manifest — the real fields

`atlas_sdk.manifest.ClusterManifest` (frozen dataclass):

| Field | Type | Notes |
|---|---|---|
| `cluster_id` | `str` | unique; rejecting duplicates |
| `name` | `str` | human label |
| `description` | `str` | defaults to `""` |
| `shared_capabilities` | `tuple[CapabilityId, ...]` | capabilities the cluster is *about* |
| `shared_contracts` | `tuple[ContractId, ...]` | contracts the cluster is *about* |
| `optional_plugins` | `tuple[str, ...]` | members that may be absent |
| `anchor_plugins` | `tuple[str, ...]` | members that define the cluster |

## Membership ≠ dependency — the critical rule

> Cluster membership does NOT mean hard dependency.

Enforced in code: `check_dependencies()` in
`atlas_core/infrastructure/registry/validation.py` inspects **only**
`manifest.requires_plugins`. `cluster_id` is never treated as a dependency.

- `requires_plugins` is the **only** hard plugin-to-plugin dependency mechanism.
- Cluster co-membership implies nothing about reachability, ordering, or
  availability. Two plugins in `cluster.workforce_and_time` may both be absent
  from an installation and the cluster is still valid.

`optional_plugins` vs `anchor_plugins` makes the intent explicit in the cluster
manifest: an optional plugin may be absent without breaking the cluster's
coherence; an anchor plugin is the one that makes the cluster what it is.

Note: `optional_plugins` / `anchor_plugins` are **declarative metadata today**.
No code path currently treats an anchor's absence as an error — they document
intent for installers and for Atlas-HQ's cluster views.

## Clusters as a graph, not a tree

Clusters are **not** a containment hierarchy (`contract.md` §6). Do not model
`Cluster A → Cluster B → Cluster C`. Business domains are cross-connected: the
real edges are contracts and events, and they cross cluster boundaries freely.

```text
                         HR CORE
                            |
              +-------------+-------------+
              |             |             |
       WORKFORCE & TIME  WORKPLACE OPS  EMPLOYEE FINANCE
              |             |             |
              +------+------+------+
                     |             |
                     v             v
                  PAYROLL       REPORTING
                     |
                     v
                DOCUMENTS
```

What this graph is **not**:

- not permission inheritance
- not dependency inheritance
- not a database foreign-key graph

What it is: a conceptual relationship map for business coherence. A plugin in
`cluster.employee_finance` may consume a contract from
`cluster.workforce_and_time` directly — no intermediate hop, no parent
permission, no shared base class.

## Which cluster a plugin joins

No formal rule beyond business coherence. The shipped plugins choose:

| Plugin | cluster_id | Why |
|---|---|---|
| `atlas_demo` | `cluster.governance_and_management` | platform plumbing belongs with platform governance |
| `atlas_demo_consumer` | `cluster.governance_and_management` | same reasoning |
| `report_studio` | `cluster.information_and_documents` | reporting is an information capability |
| `workforce_summary` | `cluster.workforce_and_time` | workforce reporting over people data |
| `attendance_summary` | `cluster.workforce_and_time` | attendance is a workforce-and-time concern |

A custom company plugin picks the cluster its business capability belongs to;
if none fits, register a new cluster first.

## Workplace naming

`contract.md` §8: the foundational workplace plugin must **not** be called
"Sites". A Site is one `WorkplaceType` among many. The real enum,
`atlas_sdk.types.WorkplaceType`: `OFFICE`, `HQ`, `BRANCH`, `SITE`, `WAREHOUSE`,
`FACTORY`, `PLANT`, `PROJECT_LOCATION`, `SERVICE_CENTER`, `REMOTE`, `OTHER`.
Construction is a configuration/type of workplace, not the platform's identity.

Last updated: 2026-09-23
