# MVENTOR MASTER EXECUTION PROMPT

## Project: ATLAS-HQ — New Platform Foundation

## Contract version: 1.4.1

## Status: GREENFIELD / DO NOT CONTINUE PRIOR IMPLEMENTATIONS

## Priority: ARCHITECTURE FIRST, THEN IMPLEMENTATION

You are starting a **new platform** from zero.

Any prior implementation is outside the scope of this contract.

Do not refactor, migrate, copy, or use a prior implementation as a technical reference.

Do not inspect prior implementation source code to understand the new architecture.

Do not assume any prior implementation decision remains valid.

A prior repository may exist only as a historical artifact and must be preserved and archived.

The new project is:

# ATLAS-HQ

Build it as a completely new platform with a new architecture.

---

# 1. THE PRODUCT IDEA

Atlas is not limited to:

> "a single-purpose HR application."

Atlas is:

> **an HR-centered modular platform capable of hosting composable business plugins.**

The foundation is:

```text
ATLAS HR CORE
      +
PLUGIN CLUSTERS
      +
PLUGINS
      +
MODULES
      +
CONTRACTS
      +
EVENTS
```

A company installs the HR Core and then composes the capabilities it actually needs.

Example:

```text
Company A

ATLAS HR CORE
```

Another:

```text
Company B

ATLAS HR CORE
+
WORKPLACE OPERATIONS
```

Another:

```text
Company C

ATLAS HR CORE
+
WORKPLACE OPERATIONS
+
ATLAS REPORT STUDIO
+
ATTENDANCE
+
FLEET
```

Another:

```text
Company D

ATLAS HR CORE
+
CLOUD DOCUMENT EXCHANGE
+
CUSTOM COMPANY PLUGIN
```

Atlas must be designed so the last example is completely legitimate.

---

# 2. THE CORE IS A REAL BUSINESS PLATFORM SERVICE

The Core is not a utilities folder.

It is not a collection of helpers.

It is not "common code."

The Core is a real service layer that Plugins consume.

The Core owns platform-wide truth and platform-wide infrastructure.

The Core must provide, at minimum:

```text
Identity & Accounts
People / Employee Identity
Organization
Jobs / Positions
Employee Assignments
Roles
Capabilities / Permissions
Scope / Context
Policy Engine
Effective-Dated Policies
Workflow Engine
Case Engine
Audit Trail
Notification Engine
Scheduling Engine
Document / Evidence Foundation
Plugin Registry
Cluster Registry
Capability Registry
Contract Registry
Event Registry
```

The Core must expose these through explicit application-facing services / interfaces.

A Plugin should be able to consume Core services through an explicit Plugin Context / SDK.

Example conceptual usage:

```python
employee = context.people.get(employee_id)

allowed = context.authorization.check(...)

scope = context.scope.resolve(...)

context.policy.evaluate(...)

context.workflow.start(...)

context.audit.record(...)

context.events.publish(...)
```

Do not make Plugins reach into Core's database tables directly.

Do not make Plugins import arbitrary internal Core implementation modules.

The Core is a platform boundary.

---

# 3. TECHNOLOGY DIRECTION

Use:

# Python

Use:

# Modular Monolith

Use:

# Hexagonal / Ports-and-Adapters architecture

Use:

# Domain-oriented boundaries

Use:

# Typed contracts / schemas

Use:

# Internal Event Bus

Use:

# PostgreSQL as the only supported database

All runtime, development, migration, and test persistence must use PostgreSQL.

No SQLite or other database engine may be used as a fallback or substitute.

Use:

# PostgreSQL Outbox pattern initially for reliable domain events

Do NOT introduce Microservices merely for architectural appearance.

Do NOT introduce Kafka / RabbitMQ / distributed infrastructure in the first foundation unless an actual requirement proves it necessary.

The objective is to establish strong modular boundaries inside one deployable application.

Later, a Plugin may be extracted into a service if necessary.

The architecture must not make that future extraction impossible.

---

# 4. THE FOUR FUNDAMENTAL LEVELS

The new architecture must distinguish these concepts everywhere:

```text
CORE
↓
CLUSTER
↓
PLUGIN
↓
MODULE
```

Do not collapse them into one concept.

## CORE

Universal Atlas platform foundation.

## CLUSTER

A coherent Business Ecosystem containing related Plugins.

## PLUGIN

A composable Business Capability Package.

## MODULE

A functional component inside a Plugin.

Example:

```text
WORKPLACE OPERATIONS CLUSTER
    |
    +-- Workplace Operations Plugin
    |      |
    |      +-- Workplace Module
    |      +-- Assignment Module
    |      +-- Workforce Module
    |
    +-- Field Operations Plugin
           |
           +-- Mission Module
           +-- Visit Module
           +-- Completion Module
```

---

# 5. NO ORPHAN PLUGINS

This is mandatory.

No Plugin may exist without belonging to a Cluster.

Even a company-specific Plugin must have a Cluster.

Example:

```text
ABC CUSTOM OPERATIONS PLUGIN
```

must belong to an appropriate Cluster.

Never allow:

```text
ATLAS
└── Random Plugin
```

All Plugins must declare:

```text
plugin_id
name
version
cluster_id
dependencies
provided_capabilities
consumed_capabilities
provided_contracts
consumed_contracts
modules
subscribed_events
published_events
```

---

# 6. CLUSTERS ARE A GRAPH, NOT A TREE

This is critical.

Do NOT model the system as:

```text
Core
  ↓
Cluster A
  ↓
Cluster B
  ↓
Cluster C
```

because real business domains are cross-connected.

Instead:

# Clusters form a Business Relationship Graph.

Example:

```text
                         HR CORE
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
      WORKFORCE & TIME  WORKPLACE OPS  EMPLOYEE FINANCE
             |              |              |
             +------+-------+-------+------+
                    |               |
                    v               v
                 PAYROLL         REPORTING
                    |
                    v
                DOCUMENTS
```

This is a conceptual relationship graph.

It is NOT permission inheritance.

It is NOT dependency inheritance.

It is NOT a database foreign-key graph.

Clusters are organized by business coherence.

Contracts and Events create the actual communication relationships.

---

# 7. INITIAL CLUSTER MAP

Create these as the initial Atlas architecture map:

```text
01. WORKFORCE & TIME
02. WORKPLACE & OPERATIONS
03. MOBILITY & FLEET
04. EMPLOYEE FINANCE
05. EMPLOYEE LIFECYCLE & DEVELOPMENT
06. EMPLOYEE SERVICES & RIGHTS
07. INFORMATION & DOCUMENTS
08. GOVERNANCE & MANAGEMENT
```

The map must remain extensible.

Do not assume this is an immutable final list.

The architecture must support new Clusters in the future.

---

# 8. INITIAL PLUGIN MAP

## WORKFORCE & TIME

```text
Attendance
Leave & Absence
Permission
Overtime
```

## WORKPLACE & OPERATIONS

```text
Workplace Operations
Field Operations
Workforce Operations
```

Important:

Do NOT name the foundational Plugin "Sites".

"Site" is only one possible Workplace Type.

Workplace Types may include:

```text
Office
HQ
Branch
Site
Warehouse
Factory
Plant
Project Location
Service Center
Remote
Other
```

Construction Sites are a configuration/type of Workplace, not the identity of the entire platform.

---

## MOBILITY & FLEET

```text
Fleet Operations
Mobility Integrations
```

---

## EMPLOYEE FINANCE

```text
Employee Finance
Payroll
```

Payroll must remain a separate Plugin even though it consumes data from many Clusters.

---

## EMPLOYEE LIFECYCLE & DEVELOPMENT

```text
Recruitment
Onboarding
People Development
Offboarding
```

---

## EMPLOYEE SERVICES & RIGHTS

```text
HR Service Desk
Employee Rights
Confidential Employee Cases
```

---

## INFORMATION & DOCUMENTS

```text
Atlas Report Studio
Document Exchange
Cloud Document Integrations
```

---

## GOVERNANCE & MANAGEMENT

```text
Governance Operations
Administrative Decisions
Policy Operations
Management Views
```

---

# 9. THE MOST IMPORTANT ARCHITECTURAL RULE

Plugins must NOT directly depend on another Plugin's implementation.

Bad:

```text
payroll.py imports attendance.py
report.py imports site_database.py
fleet.py joins payroll tables
```

Bad:

```text
Plugin A
    ↓
direct access
    ↓
Plugin B database tables
```

Forbidden.

Instead use:

```text
Capability
Contract
Command
Query
Event
```

Examples:

```text
attendance.daily_summary
overtime.approved_summary
leave.payroll_input
advance.payroll_input
workplace.workforce
fleet.trip_summary
```

The consumer cares about the contract.

It does not care who implements it.

---

# 10. SINGLE SOURCE OF TRUTH

Every important business fact must have one owner.

Example:

Attendance owns:

```text
attendance records
check-in
check-out
attendance status
attendance evidence
```

Leave owns:

```text
leave request
leave approval
leave status
leave balance
```

Overtime owns:

```text
overtime request
overtime approval
approved overtime
overtime evidence
```

Employee Finance owns:

```text
advance
repayment
expense
settlement
```

Payroll owns:

```text
payroll period
payroll run
gross
deductions
net
payroll result
```

The fact that Payroll consumes Attendance does NOT make Payroll the owner of Attendance.

---

# 11. PAYROLL IS THE REFERENCE EXAMPLE

Payroll is heavily connected to the rest of Atlas.

That is expected.

Do not solve this by making Payroll depend on every Plugin implementation.

Instead:

```text
HR CORE
   |
   +--> Employee Contract
   |
Attendance
   |
   +--> payroll.attendance_input
   |
Leave
   |
   +--> payroll.leave_input
   |
Overtime
   |
   +--> payroll.overtime_input
   |
Employee Finance
   |
   +--> payroll.advance_input
   |
   v
PAYROLL
   |
   v
PAYROLL RESULT
```

Payroll consumes contracts.

It does not own the source data.

---

# 12. HARD-CODED PLUGINS ARE ALLOWED

Atlas must support fixed Plugins.

Example:

```text
Construction Daily Workforce Report
```

A fixed Plugin may explicitly know:

```text
construction.daily_workforce
```

and produce a fixed report.

That is valid.

Do not reject hardcoded Plugins.

But recognize them as:

# Fixed / Domain-Specific Plugins

---

# 13. COMPOSABLE PLUGINS ARE ALSO REQUIRED

Atlas must support a second class:

# Composable Plugins

A Composable Plugin does not depend on the implementation name of another Plugin.

It depends on declared capabilities/contracts.

Example:

```text
REPORT STUDIO
```

does NOT say:

```python
import workplace
import attendance
import payroll
```

Instead it asks Atlas:

```text
Which installed contracts support reporting.dataset?
```

The registry may respond:

```text
workplace.workforce
attendance.daily_summary
overtime.approved_summary
payroll.summary
fleet.trip_summary
```

Report Studio can then work with whatever is installed.

---

# 14. "SMART" DOES NOT MEAN AI MAGIC

Do not implement smart composition by inspecting arbitrary database tables.

Do not implement:

```text
SELECT *
FROM every_table
```

Do not guess field meanings.

Smart composition is deterministic.

It is based on:

```text
Metadata
Capabilities
Typed Contracts
Module Declarations
Event Declarations
Registry
Adapters
```

This is the Atlas definition of a Composable Plugin.

---

# 15. MODULE CONTRACT

Every Module should be able to declare what it:

```text
Provides
Consumes
Publishes
Subscribes To
Requires
Supports
```

Example:

```yaml
module_id: workplace.workforce

provides:
  - workplace.workforce

consumes:
  - employee.assignment

publishes:
  - workplace.workforce.changed
```

Attendance:

```yaml
module_id: attendance.daily

provides:
  - attendance.daily_summary
  - payroll.attendance_input

consumes:
  - employee.assignment
  - workplace.context

publishes:
  - attendance.checked_in
  - attendance.checked_out
  - attendance.day_closed
```

---

# 16. PLUGIN MANIFEST

Every Plugin must have a manifest.

Minimum conceptual shape:

```yaml
plugin_id:
name:
version:

cluster:

requires_core:

requires_plugins:

modules:

provides_capabilities:

consumes_capabilities:

provides_contracts:

consumes_contracts:

publishes_events:

subscribes_events:
```

Do not bury this information in random Python files.

The Core must be able to inspect the Plugin declaration before enabling it.

---

# 17. PLUGIN DISCOVERY

Implement real Plugin Discovery.

Python package metadata / entry points may be used as the initial discovery mechanism.

Do not invent a fragile folder scanner.

Conceptually:

```text
Installed Package
      ↓
Atlas Plugin Entry Point
      ↓
Plugin Manifest
      ↓
Validation
↓
Registration
```

The Plugin may be distributed as a Python package in the future.

The architecture must support both:

```text
built-in Plugin
external Plugin package
```

without changing the Plugin contract.

---

# 18. PLUGIN LIFECYCLE

A Plugin must move through an explicit lifecycle:

```text
DISCOVERED
↓
VALIDATED
↓
DEPENDENCIES_CHECKED
↓
REGISTERED
↓
INITIALIZED
↓
ENABLED
↓
RUNNING
```

And support:

```text
DISABLED
STOPPED
UPGRADED
FAILED
```

A broken Plugin must not silently corrupt the Core.

---

# 19. CLUSTER MANIFEST

Clusters should also have metadata.

Conceptually:

```yaml
cluster_id:
name:
description:

plugins:

shared_capabilities:

shared_contracts:

optional_plugins:

anchor_plugins:
```

Important:

Cluster membership does NOT mean hard dependency.

Example:

```text
WORKFORCE & TIME

Attendance
Leave
Overtime
Permission
```

Overtime may optionally consume Attendance.

It should not require the implementation of Attendance unless the business capability actually requires it.

---

# 20. QUERY VS EVENT

Use Query when something needs information now.

Example:

```text
Get Employee
Get Assignment
Get Current Policy
Get Payroll Input
```

Use Events when something happened.

Example:

```text
employee.created
employee.assigned
leave.approved
overtime.approved
attendance.closed
report.generated
```

Do not use events as a universal replacement for queries.

Do not use direct table access as a universal replacement for both.

---

# 21. EVENT INFRASTRUCTURE

Initially implement:

```text
PostgreSQL Transaction
+
Outbox Event
+
Event Dispatcher
+
Internal Subscribers
```

The important guarantee is:

```text
Business State Change
+
Event Creation
```

must be transactionally reliable.

Do not start with distributed messaging infrastructure unless a real requirement appears.

The internal event system must nevertheless have a clean abstraction so a future external broker can replace the implementation.

---

# 22. DATABASE ARCHITECTURE

PostgreSQL is the exclusive database engine.

There is no SQLite runtime, fallback, compatibility, or test path.

Missing or non-PostgreSQL configuration must fail explicitly rather than select another engine.

The database schema must respect module boundaries.

Do not create one giant unowned schema where every Plugin can freely read everything.

Use clear ownership.

A Plugin should interact through:

```text
Application Services
Contracts
Repositories / Ports
Queries
Events
```

not through another Plugin's tables.

The database is an implementation detail behind the domain/application boundaries.

---

# 23. CORE SDK

Create a real internal/public SDK boundary:

# Atlas Plugin SDK

It should expose the stable contracts required by Plugins.

Conceptually:

```text
Plugin
PluginManifest
PluginContext
Module
Capability
Contract
Event
Command
Query
Registry
Service Ports
```

A Plugin developer should not need to understand every internal Core file.

They should understand the SDK.

---

# 24. ATLAS-HQ

The new application must be called:

# Atlas-HQ

Do not carry prior implementation naming or structure forward.

Atlas-HQ is the new administrative/control interface for the Atlas platform.

It must be designed around the new architecture.

It must eventually be able to:

```text
View Organization
Manage People
Manage Roles
Manage Capabilities
Manage Scopes
Install Plugins
Enable Plugins
Disable Plugins
Inspect Clusters
Inspect Modules
Inspect Contracts
Inspect Events
Configure Policies
Configure Workflows
Configure Notifications
Configure Schedules
View Audit
```

Do not build fake UI screens with no underlying architectural capability.

A UI action such as "Enable Plugin" must actually interact with the Plugin Registry/runtime.

---

# 25. THE FIRST REAL TEST

Do NOT immediately build the full HR system.

First prove that the architecture actually works.

Create a tiny real test Plugin.

For example:

# Atlas Demo Plugin

It should:

1. declare itself;
2. declare its Cluster;
3. declare one Module;
4. consume a real Core service;
5. provide one typed Contract;
6. publish one Event;
7. be discovered by the Core;
8. be registered;
9. be enabled;
10. be disabled;
11. appear in Atlas-HQ;
12. write to Audit;
13. obey a Capability;
14. obey Scope.

Then create a second tiny Plugin that consumes the first Plugin's Contract.

This proves:

```text
Plugin A
   ↓
Contract
   ↓
Plugin B
```

without direct imports/database coupling.

---

# 26. REPORT STUDIO MUST BECOME THE SECOND ARCHITECTURAL PROOF

After the demo:

Build the initial:

# Atlas Report Studio

as a Composable Plugin.

It must not hardcode:

```text
Site
Attendance
Payroll
Fleet
```

Instead it must discover compatible reporting contracts.

For example:

```text
workplace.workforce
attendance.daily_summary
overtime.approved_summary
payroll.summary
fleet.trip_summary
```

Then a report definition can consume whichever are installed and compatible.

The goal is to prove:

```text
Install Plugin A
      ↓
Report Studio discovers capability
      ↓
Install Plugin B
      ↓
Report Studio discovers another capability
      ↓
No Report Studio code modification
```

This is a mandatory architectural acceptance test.

---

# 27. FIRST REAL DOMAIN PLUGIN

After the architecture proof:

Build:

# Workplace Operations

NOT "Sites".

A Workplace can be:

```text
Office
HQ
Branch
Site
Warehouse
Factory
Plant
Project Location
Service Center
```

Construction is simply one Workplace Type.

The Workplace Plugin should provide actual business services, not mock records.

---

# 28. CONSTRUCTION REPORTING COMES AFTER THE FOUNDATION

The construction daily workforce reporting use case remains valid as a business use case.

However:

Do not rebuild it using the structure of a prior implementation.

Instead:

```text
HR Core
+
Workplace Operations
+
Atlas Report Studio
```

Workplace provides structured operational data.

Report Studio consumes the appropriate Contracts and generates the report.

---

# 29. PRIOR REPOSITORY BOUNDARY

Any prior repository is outside Atlas-HQ.

Preserve its Git history.

Do not delete it.
Do not rewrite its history.
Do not migrate its source into Atlas-HQ.
Do not copy its source into Atlas-HQ.
Do not depend on it.

Do not inspect its source as an architectural reference for Atlas-HQ.

Repository metadata may be inspected only for preservation and archival purposes.

After archival, treat it as read-only historical material.

---

# 30. ABSOLUTE "DO NOT" LIST

Do not:

```text
continue or refactor a prior implementation
migrate prior implementation architecture
copy prior implementation modules
reuse a prior implementation database schema by default
assume prior implementation naming is correct
hardcode prior product names into Core
hardcode Site into Core
hardcode reports into individual Domains
make Payroll own all incoming business data
let Plugins read each other's tables
let Plugins bypass the Core
let Plugins bypass Contracts
create orphan Plugins
make Cluster membership equal dependency
make everything a Microservice
build a fake Plugin system
build a folder-scanning pseudo-plugin loader
```

---

# 31. ARCHITECTURAL ACCEPTANCE GATES

Do not declare the foundation complete until all of these are demonstrated.

## Gate A — Clean Greenfield

Atlas-HQ builds and runs independently from any prior implementation.

## Gate B — Core Services

At least several Core services are real and callable.

## Gate C — Plugin Discovery

A Plugin can be discovered without manually editing Core code.

## Gate D — Cluster Registration

The Plugin is registered under a Cluster.

## Gate E — Module Registration

Its Modules appear in the Registry.

## Gate F — Capability Registration

Its capabilities are discoverable.

## Gate G — Contract Registration

Its contracts are discoverable.

## Gate H — Event Registration

Its events are discoverable.

## Gate I — Plugin Enable/Disable

Plugin lifecycle works.

## Gate J — Core Consumption

The Plugin consumes a real Core service.

## Gate K — Plugin-to-Plugin Communication

Plugin B consumes a Contract provided by Plugin A without importing Plugin A implementation.

## Gate L — Audit

Plugin operations generate real Audit records.

Core Roles Engine grant and assignment changes are explicitly audited, and report authorization outcomes are auditable as required by §38.

## Gate M — Authorization

Role grants and web, Telegram, and AI actions obey Core-owned effective permissions, confirmation, and the §38 default-deny rule. Plugins cannot self-authorize.

## Gate N — Scope

Plugin data and channel actions respect matching Scope, including the self-scope isolation and channel parity required by §38.

## Gate O — Composable Reporting

Report Studio consumes at least two different Plugin-provided datasets without changing Report Studio source.

The first on-demand `self.monthly.report` use case satisfies §38 without adding self-specific logic to Core or Report Studio.

---

# 32. TESTING REQUIREMENT

Every architectural concept must have automated tests.

Acceptance tests must run against a real PostgreSQL database with per-test isolated state.

SQLite, in-memory database engines, and mocks are not substitutes.

Acceptance coverage must include:

```text
schema creation
commit and rollback
outbox atomicity
no state leakage between tests
```

At minimum:

```text
Core tests
Plugin Registry tests
Cluster Registry tests
Capability tests
Contract tests
Event tests
Lifecycle tests
Dependency tests
Scope tests
Authorization tests
Audit tests
Plugin SDK tests
Composable Plugin tests
Report Studio integration tests
Core Roles Engine tests
Role grant and assignment tests
Scope isolation tests
Web / Telegram / AI authorization parity tests
AI fallback tests
`self.monthly.report` on-demand integration tests
```

Do not rely only on manual UI testing.

---

# 33. DOCUMENTATION REQUIREMENT

Before expanding into many Business Modules, create:

```text
ARCHITECTURE.md
CORE_CONSTITUTION.md
PLUGIN_SPEC.md
CLUSTER_SPEC.md
MODULE_SPEC.md
CONTRACT_SPEC.md
EVENT_SPEC.md
PLUGIN_SDK.md
DEVELOPMENT_GUIDE.md
```

The documentation must describe the rules that future Mventor sessions can follow without rediscovering the architecture.

---

# 34. HOW YOU SHOULD WORK

Do not behave like a developer waiting for individual tickets.

Act as the implementation owner of this greenfield architecture.

Work in phases.

At the end of each phase:

```text
run tests
run type checks
run lint/format checks where configured
verify runtime behavior
inspect changed files
commit
```

Keep commits coherent and explain what architectural rule each major commit establishes.

Do not prematurely expand into dozens of business features.

Build the foundation until it is demonstrably capable of hosting the first real Plugins.

---

# 35. WHEN YOU ENCOUNTER UNCERTAINTY

Use these rules:

```text
New reusable platform primitive
→ consider Core

Business capability for a specific business domain
→ Plugin

Group of related Business capabilities
→ Cluster

Functional piece of a Plugin
→ Module

Who may perform an action
→ Capability

Which records/data are affected
→ Scope

Business rule
→ Policy

Lifecycle
→ Workflow

What happened
→ Event

Current information needed now
→ Query

Historical accountability
→ Audit
```

Never solve ambiguity by copying prior implementation architecture.

Never use a prior codebase as the answer.

The new architecture has priority.

---

# 36. FINAL PRODUCT PRINCIPLE

Atlas must eventually support this:

```text
ATLAS HR CORE
      |
      +--- WORKFORCE & TIME CLUSTER
      |
      +--- WORKPLACE & OPERATIONS CLUSTER
      |
      +--- EMPLOYEE FINANCE CLUSTER
      |
      +--- MOBILITY & FLEET CLUSTER
      |
      +--- INFORMATION & DOCUMENTS CLUSTER
      |
      +--- CUSTOM COMPANY PLUGINS
```

And:

```text
Payroll
```

may consume contracts from many Clusters.

```text
Report Studio
```

may consume contracts from many Clusters.

```text
Notification Automation
```

may subscribe to events from many Clusters.

This is allowed.

What is forbidden is implementation coupling.

The Atlas architecture should therefore optimize for:

# HIGH CONNECTIVITY

with

# LOW COUPLING

not for artificial isolation.

---

# 37. FIRST MISSION

Your immediate mission is NOT:

"build all HR."

Your immediate mission is:

```text
1. Create Atlas-HQ greenfield.
2. Establish the repository structure.
3. Establish Atlas HR Core.
4. Establish Plugin SDK.
5. Establish Plugin / Cluster / Module / registries.
6. Establish Capability and Contract system.
7. Establish internal Event Bus + Outbox foundation.
8. Create Demo Plugin A.
9. Create Demo Plugin B consuming A.
10. Demonstrate real Core service usage.
11. Demonstrate Plugin discovery.
12. Demonstrate Enable/Disable.
13. Demonstrate Audit / Authorization / Scope.
14. Establish Report Studio as first Composable Plugin proof.
15. Establish Workplace Operations as first real Domain Plugin.
16. Only then begin expanding business functionality.
17. Preserve and archive any prior repository; leave it untouched and read-only.
```

Do not stop after creating empty folders or interfaces.

The foundation must demonstrate actual runtime behavior.

The objective is not to make Atlas-HQ "look modular."

The objective is to make Atlas-HQ **architecturally capable of receiving new business capabilities as Lego pieces without rewriting the Core**.

# 38. CORE ROLES ENGINE, USE-CASE METADATA, AND FIRST ON-DEMAND SELF REPORT

## 38.1 USE-CASE METADATA

Every report definition must declare its use case with at least:

```text
use_case_id (stable)
title
summary
owner
audience
scope
date_grain
required_capabilities
surfaces
review_status
version
```

The `use_case_id` must remain stable across descriptive changes. Optional future schedule metadata may be added later, but it is not required for the first release.

## 38.2 CORE ROLES ENGINE OWNERSHIP

The Core Roles Engine is the sole owner of principals, roles, capabilities, user grants and assignments, Scope, effective permissions, policy, Audit, and confirmation state.

Plugins may declare capability and role metadata only. They cannot create or widen their own authorization, grant capabilities to principals, bypass Core policy or confirmation, or otherwise self-authorize. Core validates and records all effective authorization.

## 38.3 EXPLICIT GRANTS AND CAPABILITY KINDS

Selecting a user and checking a feature must create an explicit audited grant for that Core principal.

Role bundles may be reusable groupings of capability and Scope metadata, but their assignment must also be audited and must resolve through the same explicit effective-authorization model.

The server must recheck effective authorization when an action is executed. Checked UI state, a role label, or a Plugin declaration is never sufficient by itself.

These are separate capability kinds and are not interchangeable:

```text
view
schedule
manage
```

The `schedule` capability kind does not require a scheduler or scheduled delivery in the first release.

## 38.4 CHANNEL-NEUTRAL PRINCIPALS AND PARITY

Core principals are channel-neutral. Web, Telegram, and AI are channels that must apply the same Core identity, grant, Scope, policy, Audit, and confirmation rules.

A Telegram identity starts untrusted and has no permissions until it is linked to an authenticated Core principal. A channel identity never grants permission by itself.

AI access additionally requires the `assistant.use` capability. AI cannot bypass Core policy or confirmation.

## 38.5 DEFAULT-DENY AUTHORIZATION

A request is allowed only when all of these conditions are true:

```text
authenticated Core principal
AND required capability
AND matching Scope
AND policy allows the action
AND the requested channel action is enabled
```

Missing any condition denies the request. This default-deny rule applies equally to web, Telegram, AI, Plugins, and Core services. Any required confirmation is part of policy and effective authorization and cannot be skipped.

## 38.6 FIRST ON-DEMAND SELF REPORT

`self.monthly.report` is a module/use case owned by a reporting Plugin, belongs to `cluster.information_and_documents`, and has `scope=self`.

The first release is on-demand only. Scheduled delivery is explicitly deferred and is not an acceptance requirement.

Atlas Report Studio remains generic. Neither Core nor Report Studio may contain self-specific logic for this use case.

## 38.7 ACCEPTANCE REQUIREMENTS

The foundation is accepted only when automated tests demonstrate all of the following:

- `self.monthly.report` has complete stable metadata, runs on demand, returns only the requesting principal's self-scoped data, and requires no scheduler.
- Selecting a user and checking a feature creates an explicit audited grant; reusable role bundles resolve through the same model, and the server rechecks effective authorization.
- Self-scope isolation prevents one principal from viewing or managing another principal's self report.
- Web, Telegram, and AI authorization parity is demonstrated through the same Core principal, capability, Scope, policy, confirmation, and channel-action rules; an unlinked Telegram identity is denied.
- Grant creation and change, role assignment, identity linking, confirmation, and self-report access produce the required Audit evidence.
- AI fallback is safe: when principal linkage, `assistant.use`, effective authorization, policy, or confirmation is missing, AI must not perform the action or infer permission. It must return an explicit denial and direct the user to an authorized web or linked Telegram flow, which must independently reauthorize.

## 38.8 OPAQUE EXECUTION HANDLE

Every execution that reaches a public Core boundary must receive a server-issued, opaque `ExecutionHandle`. The handle is a non-forgeable reference, not a mutable security-facts container. The SDK must expose no mutable principal, channel, action/operation, resource, Scope, or policy fields to plugins.

Core persists the canonical execution record and resolves each handle to that record. Only Core may issue, resolve, revoke, or expire handles. Plugins, callers, payloads, actor IDs, and plugin metadata cannot construct, alter, extend, replace, or spoof a handle or any fact resolved from it. An unknown, invalid, revoked, or expired handle fails closed.

## 38.9 CONTEXT PROPAGATION AND PUBLIC ENTRY POINTS

Contract handlers, direct plugin methods, dataset/report calls, and CLI paths must receive and propagate the same valid `ExecutionHandle`. Context is mandatory, not optional, at every public boundary; these paths must not reconstruct it from request payloads, actor IDs, role labels, or plugin metadata. Every direct Core path, Plugin path, CLI path, contract handler, and dataset/report call requires a valid handle and fails closed when it is missing or invalid. No caller may supply an unauthenticated fallback handle or context.

## 38.10 CORE-OWNED POLICY AND CANONICAL FACTS

Core alone owns policy registration and evaluation. Plugin metadata may describe requested capabilities or roles, but it cannot install, register, mutate, override, or otherwise alter policy. Caller payload facts cannot override the canonical execution facts resolved by Core from the handle, including principal, identity, channel, action/operation, resource, Scope, and policy context.

Plugin persistence is restricted to plugin-owned tables and operations. Arbitrary Core-table access, raw Core-session access, and arbitrary access to another plugin's persistence are forbidden. Plugins must use Core services, contracts, and approved plugin-owned persistence rather than direct Core database access.

## 38.11 PERSISTENT UNIT OF WORK AND ATOMICITY

Production management and authorization require a persistent PostgreSQL Unit of Work (UoW). Registry-only boot is explicitly database-free and non-authorizing; it cannot authorize, serve data, mutate protected state, or perform protected management. A missing, unavailable, or incorrectly scoped UoW fails closed.

Allowed authorization decisions and their mutations remain atomic: the decision, business mutation, and required business-state/audit/event changes must share the same successful transaction boundary. A denied decision must still produce durable, fail-closed Audit through a safe Core audit path, even when the business transaction rolls back. A caller or plugin cannot bypass that path.

## 38.12 ONE-TIME CONFIRMATIONS AND IDENTITY LINKING

Typed confirmations and identity links are one-time and concurrency-safe. Core must use row locks, conditional updates, or an equivalent atomic PostgreSQL operation so concurrent requests cannot both consume the same confirmation or complete the same link. Each confirmation or link is bound to the canonical execution facts resolved from the handle, including principal, capability, action, resource, and Scope; a mismatch, replay, or already-consumed state is denied.

## 38.13 CONTEXT-AWARE READS AND DEFAULT DENY

All data reads, including reporting datasets and report generation, must enforce the valid `ExecutionHandle`, authenticated principal, effective capability, Scope, policy, and default deny. No plugin, dataset, or report path may infer or widen context, identity, or Scope from a request payload or actor ID. The existing `self.monthly.report` remains on-demand and self-scoped; this amendment does not add self-specific logic to Core or Report Studio and does not authorize scheduler or transport implementation.

## 38.14 SECURITY ACCEPTANCE TESTS

The automated acceptance suite must add or adjust adversarial tests for all of the following:

- forged, mutated, replayed, expired, revoked, or unknown `ExecutionHandle` values are rejected, and a handle cannot be constructed or modified to impersonate another execution;
- handle propagation is verified through contract handlers, direct plugin methods, dataset/report calls, and CLI paths;
- principal, channel, action/operation, resource, Scope, policy, and other caller-payload fact spoofing is rejected and cannot override canonical execution facts;
- every protected path fails closed when a handle is missing or invalid, and no fallback context is accepted;
- plugins can access only their own tables/operations; cross-table, arbitrary Core-table, raw-session, and other-plugin persistence access is rejected;
- policy registration and evaluation remain Core-only, and plugin metadata cannot install, register, mutate, override, or alter Core-owned policy;
- production management and authorization without a persistent PostgreSQL UoW fail closed, while registry-only boot remains database-free and non-authorizing and cannot serve data;
- a denied decision creates a durable, fail-closed denial Audit record even when the business transaction rolls back;
- concurrent typed-confirmation attempts and identity-link attempts are race-safe, with at most one success for each one-time operation; and
- reporting and other data reads cannot bypass handle resolution, authenticated principal, effective capability, Scope, policy, or default-deny enforcement.

## 38.15 VERSIONED MIGRATION BOUNDARY

Any deployed schema changes required by this security hardening amendment, including canonical execution-record and handle persistence, must be delivered through a future versioned migration. `create_all` is not a migration and must not be used to upgrade or replace migrations for deployed databases.

## 38.16 PLUGIN TRUST BOUNDARY

Atlas-HQ plugins are trusted in-process application code inside the current modular monolith. The rules in §§38.8–38.15 are a boundary against ordinary and accidental violations, not a sandbox for a hostile adversary. The SDK/Core public boundary, the `ExecutionHandle`, restricted plugin-owned persistence, Core-only policy and role ownership, and mandatory context at every public entry point are what prevent accidental or ordinary boundary violations.

Low-level Python introspection and deliberately malicious plugin code are outside the current threat model. In-process plugins share the interpreter and can reach module and process state, so no in-process arrangement makes that case safe. This contract does not claim, test, or support it as a security boundary.

Untrusted or third-party plugins are not admitted by this contract. Admitting them requires a future out-of-process isolation architecture — separate process, enforced capability RPC, and no shared interpreter state — which is out of scope here and a prerequisite to any change in plugin admission.

Nothing here weakens the rules above. Default deny, capability and Scope checks, Audit requirements, Core ownership of policy and roles, and plugin table-ownership restrictions all remain in force unchanged. The `self.monthly.report` use case remains on-demand and self-scoped, and this section does not authorize any scheduler or transport implementation.

# 39. WEB UI DESIGN TOKENS — LIGHT AND DARK PALETTES

## 39.1 SOURCE OF TRUTH

The semantic tokens in §39.2 are the authoritative source of truth for the Atlas-HQ web UI. Framework and library variables, including shadcn/ui and Tailwind CSS variables, are derived mappings of these tokens and never redefine them. Components must reference semantic token names and must never contain raw hex values.

## 39.2 TOKEN TABLE

Both themes use the same semantic token names.

| Semantic token | Light | Dark | Status |
| --- | --- | --- | --- |
| `bg.canvas` | `#F7F2EB` | `#41444B` | Supplied palette |
| `bg.surface` | `#EAE2D6` | `#52575D` | Supplied palette |
| `border.divider` | `#EEEEEE` | `#52575D` | Supplied palette; decorative only in both themes |
| `accent.default` | `#8B9A6E` | `#CABFAB` | Supplied palette |
| `fg.default` | `#2D0000` | `#DFD8C8` | Light derived, dark supplied |
| `border.control` | `#757D6F` | `#DFD8C8` | Light derived, dark supplied |
| `onAccent.default` | `#2D0000` | `#41444B` | Derived for contrast |
| `focus.ring` | `#2D0000` | `#DFD8C8` | Derived for contrast; dark value is canvas and surface only |
| `focus.ring.onAccent` | `#2D0000` | `#41444B` | Derived for contrast; required on accent-filled controls |
| `state.success` | `#2D0000` on `#C7D3C0` | `#2D0000` on `#C7D3C0` | Text/fill pair; provenance in §39.4 |
| `state.success.indicator` | `#2A7C13` on `#C7D3C0` | `#2A7C13` on `#C7D3C0` | Non-text indicator pair only; never normal text |
| `state.warning` | `#2D0000` on `#C8A96B` | `#2D0000` on `#C8A96B` | Text/fill pair; provenance in §39.4 |
| `state.danger` | `#6D0808` on `#FFDADA` | `#6D0808` on `#FFDADA` | Text/fill pair; provenance in §39.4 |
| `state.info` | `#2D0000` on `#FBE6C2` | `#2D0000` on `#FBE6C2` | Text/fill pair; provenance in §39.4 |

A `state.*` cell is a text and fill pair, not a single color, and the two are never separated. The left value is the ink and the right value is the fill it sits on. A component reads both from the same token name so a state cannot be rendered with a mismatched ink and fill.

`state.success.indicator` is the one carve-out from that rule. It is a non-text pair: it draws a success icon, a success border, or a large or bold success badge, and it is never the ink of normal-size text. It exists because `#2A7C13` measures 3.38:1 on `#C7D3C0` and therefore clears the 3:1 non-text minimum while failing 4.5:1, and because a success state with no distinguishable green of its own is a weaker signal than the palette already allows. It is additive, never a replacement for `state.success`.

`focus.ring` and `focus.ring.onAccent` are one role with a per-theme value, and a focus indicator never mixes them. `focus.ring` is the ring on `bg.canvas` and `bg.surface`. `focus.ring.onAccent` is the ring on an accent-filled control, and §39.5 requires it there. Both roles exist in both themes, as §39.5 requires of every role.

`#EEEEEE` is a `border.divider` value only. Any use of `#EEEEEE` as `bg.muted`, as any other background, or as any text color is removed and forbidden.

`fg.muted` is deliberately not a table cell and deliberately has no hex value. It is derived from `fg.default` in each theme, it must reach 4.5:1 against the background it is used on, and it is confirmed by the automated check in §39.5 before use. `#EEEEEE` is not an available value for it under any condition. This is the only role still open, and it is settled by measurement rather than by palette.

No cell in this table is UNRESOLVED. Every role is now decided. Any later change to a value here is a contract amendment, not a component decision.

## 39.3 TOKEN ROLES AND PROHIBITIONS

- `accent.default` is never body text, paragraph text, or link text. It is an emphasis, control, and highlight color only.
- `state.success.indicator` is never normal-size text and never the only signal of success. It is a non-text indicator, and it is used beside the `state.success` text or beside an icon, never instead of it.
- `focus.ring` is drawn on `bg.canvas` and `bg.surface` only. An accent-filled control uses `focus.ring.onAccent`, and drawing `focus.ring` on `accent.default` in the dark theme is forbidden because it measures 1.28:1 there.
- `#EEEEEE` and `border.divider` are never text and never a fill. A divider is a boundary, not content.
- Control boundaries, including input, select, checkbox, and button outlines, use `border.control` and not `border.divider`.
- Raw hex values are forbidden in components. Only semantic token names may appear in component source.
- Color is never the sole indicator of state, severity, or meaning. Color must always be paired with text, an icon, or another non-color signal.

## 39.4 RESOLVED VALUES, SOURCES, AND MEASURED CONSTRAINTS

The Color Hunt palettes that supplied the values are:

- Light base palette: https://colorhunt.co/palette/8b9a6ef7f2ebeae2d6eeeeee
- Dark base palette: https://colorhunt.co/palette/41444b52575ddfd8c8cabfab
- Sage supporting palette: https://colorhunt.co/palette/8fa28ac7d3c0f7f4edc8a96b
- Warm supporting palette: https://colorhunt.co/palette/fbe6c2fff8cf76c4572a7c13

These palettes supply colors, not semantic roles. Every role assignment in §39.2 is an Atlas decision, and no palette is a source of authority for a role.

Twelve values are literal members of those palettes and four are Atlas-derived. The split is recorded here because a derived value carries no palette authority and must survive the automated check on its own:

- Literal palette members: `#F7F2EB`, `#EAE2D6`, `#EEEEEE`, `#8B9A6E`, `#41444B`, `#52575D`, `#DFD8C8`, `#CABFAB`, `#C7D3C0`, `#C8A96B`, `#FBE6C2`, `#2A7C13`.
- Atlas-derived: `#2D0000`, `#6D0808`, `#FFDADA`, `#757D6F`.

`#2D0000` is the load-bearing derived value. It is the deep warm red that sits in the same family as the light accent, and it serves as light body ink, both light on-accent ink and focus ring, the light focus ring on an accent fill, the light and dark success ink, and the ink on the light tint fills. `#FFDADA` is a derived danger tint that has no palette member. `#6D0808` is derived to sit on that tint. `#757D6F` is a derived light control border. `#41444B` is the supplied dark canvas reused as the dark on-accent ink, and it is the same reuse that makes it the dark focus ring on an accent fill.

`#2A7C13` is a literal warm-palette member and it keeps exactly one role, a non-text success indicator. It is not the success ink. The success ink is the derived `#2D0000`, which measures 12.15:1 on `#C7D3C0` against the 3.38:1 that `#2A7C13` reaches there, so no size restriction is needed for success text. Demoting a supplied palette value out of the text role costs nothing: the palette supplies colors, not roles, and §39.1 makes §39.2 the authority for roles.

`border.control` in dark theme is `#DFD8C8`, the supplied dark foreground, reused as the control boundary. This is a deliberate contrast-safe derived choice, not a palette pairing: no mid-tone from any verified Color Hunt palette was found to reach the 3:1 non-text minimum against `#41444B` or `#52575D`. Reusing the supplied foreground reuses a value already verified at 6.87:1 and 5.14:1 against those two backgrounds.

The state fills and inks measure as follows. These are automated measurements, not estimates, and the check required by §39.5 re-runs them:

| Pair | Measured | Minimum | Result |
| --- | --- | --- | --- |
| light `fg.default` on `bg.canvas` | 16.96:1 | 4.5:1 | Pass |
| light `fg.default` on `bg.surface` | 14.71:1 | 4.5:1 | Pass |
| light `border.control` on `bg.canvas` | 3.83:1 | 3:1 | Pass |
| light `border.control` on `bg.surface` | 3.32:1 | 3:1 | Pass |
| light `onAccent.default` on `accent.default` | 6.25:1 | 4.5:1 | Pass |
| light `focus.ring` on `bg.canvas` | 16.96:1 | 3:1 | Pass |
| light `focus.ring` on `accent.default` | 6.25:1 | 3:1 | Pass |
| light `focus.ring.onAccent` on `accent.default` | 6.25:1 | 3:1 | Pass |
| light `state.success` ink on fill | 12.15:1 | 4.5:1 | Pass |
| light `state.success.indicator` on fill | 3.38:1 | 3:1 | Pass, non-text only |
| light `state.warning` ink on fill | 8.41:1 | 4.5:1 | Pass |
| light `state.danger` ink on fill | 9.65:1 | 4.5:1 | Pass |
| light `state.info` ink on fill | 15.47:1 | 4.5:1 | Pass |
| light `accent.default` on `bg.canvas` | 2.71:1 | 3:1 | **Fails**, as a non-boundary fill only |
| dark `fg.default` on `bg.canvas` | 6.87:1 | 4.5:1 | Pass |
| dark `fg.default` on `bg.surface` | 5.14:1 | 4.5:1 | Pass |
| dark `border.control` on `bg.canvas` | 6.87:1 | 3:1 | Pass |
| dark `border.control` on `bg.surface` | 5.14:1 | 3:1 | Pass |
| dark `onAccent.default` on `accent.default` | 5.36:1 | 4.5:1 | Pass |
| dark `focus.ring` on `bg.canvas` | 6.87:1 | 3:1 | Pass |
| dark `focus.ring` on `accent.default` | 1.28:1 | 3:1 | **Not a permitted pair**, see below |
| dark `focus.ring.onAccent` on `accent.default` | 5.36:1 | 3:1 | Pass |
| dark `border.divider` on `bg.canvas` | 1.34:1 | 3:1 | **Fails**, decorative only |
| dark `accent.default` on `bg.canvas` | 5.36:1 | 3:1 | Pass |
| dark `state.*` ink on fill | 8.41:1 to 15.47:1 | 4.5:1 | Pass |

Three measured facts survive into §39.5 as binding rules rather than as apologies.

The light success ink is now the derived `#2D0000` on `#C7D3C0`, which measures 12.15:1 and clears 4.5:1 outright. The 3.38:1 shortfall that `#2A7C13` produced on that fill is no longer reachable by any text role, so there is no size restriction on success text and no deferred amendment. The measured 3.38:1 survives only as `state.success.indicator`, a non-text pair that §39.3 confines to icons, borders, and large or bold badges.

The dark `focus.ring` `#DFD8C8` measures 1.28:1 on the dark accent fill `#CABFAB` and is therefore not a usable focus indicator on an accent-filled control. This is a gap in the token, not a tolerance to be argued, and it is closed by the `focus.ring.onAccent` token: `#41444B` on `#CABFAB` measures 5.36:1. That token is required on an accent-filled control and `focus.ring` is forbidden there, so the indicator no longer depends on a second ring being remembered at call time.

Both `border.divider` values are decorative. Light `#EEEEEE` measures 1.04:1 on `bg.canvas` and dark `#52575D` measures 1.34:1 on `bg.canvas` and 1.0:1 on `bg.surface`. These are the two lowest-contrast tokens in the table by design, and that is accepted deliberately rather than overlooked.

## 39.5 ACCESSIBILITY REQUIREMENTS

- Body and paragraph text must reach a contrast ratio of at least 4.5:1 against its background.
- Large text and non-text elements, including control boundaries, meaningful dividers, icons, and focus indicators, must reach at least 3:1.
- Every interactive control must show a visible focus indicator that meets 3:1 against its adjacent colors.
- An accent-filled control must draw its focus indicator in `focus.ring.onAccent`. Drawing `focus.ring` on `accent.default` in the dark theme is forbidden at 1.28:1, and adding a second ring at call time is not a substitute for the token.
- Contrast must be verified by an automated check and not by eye, and that check must cover every token pair in §39.2 in both themes.
- The check must cover every interactive pair, which means each `state.*` ink on its own fill, each `state.*` non-text indicator on its own fill, `onAccent.default` on `accent.default`, `border.control` against both backgrounds, `focus.ring` against every background it may be drawn on, and `focus.ring.onAccent` against an accent fill. A pair that is only measured against one background has not been checked, and a pair §39.3 forbids must be reported as a forbidden pair rather than as a pass.
- The check must run in CI, and a failing pair blocks the change that introduced it. A ratio recorded in §39.4 is evidence, not a substitute for the run.
- Both themes use the same semantic token names. A role that exists in one theme must exist in the other, so no surface needs a theme-specific token name.
- Thresholds follow W3C WCAG 2.1 SC 1.4.3 (Contrast Minimum) and SC 1.4.11 (Non-text Contrast).

Exactly three exceptions are permitted, and they are narrow and named: the light `border.divider` value, the dark `border.divider` value, and the `state.success.indicator` size restriction. No other pair in §39.2 is exempt, and no exception covers normal-size text.

`border.divider` is exempt from 3:1 in both themes because both values are decorative. A divider is exempt only where it carries no meaning. It is never a control boundary, never a focus indicator, never the sole indicator of grouping, state, or severity, and never the only thing separating an interactive element from its background. Where a divider separates regions whose relationship matters, `border.control` is used instead. A decorative divider still requires a non-color signal where it marks state.

`state.success.indicator` is exempt from 4.5:1 because it is exempt from being text. `#2A7C13` measures 3.38:1 on `#C7D3C0` and clears the 3:1 non-text minimum, so it is allowed for a success icon, a success border, or a large or bold success badge, and forbidden as normal-size text in every theme. This exemption is a size and role restriction on that one pair, it is not a precedent for any other token, and it does not reach `state.success`, which measures 12.15:1 and needs no exemption at all.

An accent fill is a fill and not a boundary, so the 2.71:1 measured for the light `accent.default` against `bg.canvas` is not a non-text failure and is not a fourth exception. The 3:1 requirement lands on `border.control` and on the focus indicator, which is why §39.3 routes control boundaries to `border.control` and not to `border.divider` or the accent fill.

## 39.6 DEFAULT THEME AND PERSISTENCE

The default theme is light. A principal with no stored preference renders light, not a dark theme inferred from the environment.

The theme preference is a Core-owned property of the principal, consistent with the Core ownership rule in §38.2, and it follows the principal across web, Telegram, and AI channels.

Browser `prefers-color-scheme` is an input to that preference, not the preference itself. It may seed the first render for a principal who has never chosen, and it is only consulted while no Core-owned value exists. Once a principal sets a theme, that stored value wins over `prefers-color-scheme` on every channel, and a later change to the operating system setting must not silently override an explicit user choice.

The browser may mirror the Core-owned preference locally only to prevent a light or dark flash before Core responds. A browser-local copy is a rendering cache and not the source of truth, and a theme set on one channel must not be stranded on one device. The local mirror is optional: a surface that shows a brief unstyled or light-first render is conformant, and skipping the mirror is preferred over storing a value that can disagree with Core.

A new persisted principal preference field must be delivered through a future versioned migration under §38.15. `create_all` is not a migration.

## 39.7 BOUNDARY

This section is a product and design contract only. It does not prescribe a frontend framework, router, build tooling, CSS pipeline, or component implementation, and it authorizes no fake UI, placeholder screen, or mock surface. A UI action must still interact with a real capability as required by §24.

This section does not relax §24 or §38. Authorization, default deny, Scope, Audit, capability, and Core ownership rules are unchanged, and theme selection is a presentation preference that never grants, widens, or bypasses any capability.

## 39.8 UI STACK BOUNDARY

shadcn/ui with Tailwind CSS variables is the expected component approach for the web UI if it is feasible at implementation time. Under this approach:

- shadcn/ui components are copied into the Atlas-HQ repository and owned by the project. They are not consumed from an upstream package.
- The shadcn CLI is not a build step, not a runtime dependency, and not a required part of any build or test pipeline.
- Tailwind variables map to the semantic tokens in §39.2 and never override them.

The mapping is:

| Atlas token | shadcn/Tailwind variable |
| --- | --- |
| `bg.canvas` | `--background` |
| `bg.surface` | `--card` |
| `border.divider` | `--border` |
| `border.control` | `--input` |
| `accent.default` | `--primary` |
| `onAccent.default` | `--primary-foreground` |
| `fg.default` | `--foreground` |
| `fg.muted` | `--muted-foreground` |
| `focus.ring` | `--ring` |
| `focus.ring.onAccent` | `--focus-ring-on-accent` |
| `state.*` | a fill variable and a foreground variable per state, matching the pair in §39.2 |
| `state.success.indicator` | `--success-indicator`, a non-text pair matching the row in §39.2 |

`--muted-foreground` maps to the derived `fg.muted` role, not to a hex. A mapped variable that has no token behind it is not allowed to invent one, and no Tailwind variable may introduce a color that §39.2 does not record.

`--focus-ring-on-accent` and `--success-indicator` are Atlas-defined companions with no shadcn primitive behind them. They exist because §39.2 records `focus.ring.onAccent` and `state.success.indicator` as required roles, and a required role needs a variable. They are added alongside `--ring` and the state variables and never override them, and they are bound to the token values in §39.2 rather than to a hex of their own.

If shadcn/ui later proves infeasible, the semantic tokens in §39.2 and the accessibility rules in §39.5 remain binding, and only the component library changes. The token contract does not depend on the library.

# 40. INSTALLER AND LOCAL DEMO LAUNCHER

## 40.1 SCOPE

`install.ps1` is the supported Windows installer for Atlas-HQ and is published as an asset of a GitHub Release. `start-demo.ps1` is a committed local demo launcher that lives in the repository rather than in a release.

Neither script is Core, a Plugin, a Cluster, a Module, a capability, or a Contract. Neither adds an architectural gate, and neither is a substitute for any gate already required by §31. They are packaging and distribution surface around the platform, not a new level in §4.

## 40.2 INSTALLER SAFETY

`install.ps1` must not:

```text
request, require, or attempt Administrator elevation
modify, relax, or bypass the PowerShell execution policy
download or execute a remote script, including itself
embed, generate, print, or persist a secret
write to a production or remote database
create, alter, or migrate a schema through `create_all`
```

The only locations `install.ps1` may write are its own install directory and user-local locations it already owns, including a user-local virtual environment and the user-local npm cache. It must not write outside those locations, and it must not require a machine-wide install in order to succeed.

`install.ps1` never migrates a schema. A schema change is delivered by a versioned migration under §38.15, and `create_all` is not a migration.

## 40.3 DEMO SAFETY

`start-demo.ps1` must:

```text
bind every listener to loopback only
use a development login that exists only for the child process it starts
require an explicit operator-init flag and never run operator-init silently
never pass a remote database URL or an allow-remote flag
track every process it starts and stop the tracked set on exit
```

The demo is a local development convenience. Its development login is scoped to the child process and expires with it. It is not a production credential and not a path to one. A demo run that cannot bind loopback fails; it does not widen its own binding to reach a browser.

## 40.4 SUPPLY CHAIN

An installer is distributed only as an asset of a tagged GitHub Release. The release carries the exact source bundle the installer is proven against, so the artifact and the tested source are the same thing.

A SHA-256 checksum file named `SHA256SUMS.txt` sits beside `install.ps1` in the release assets, and the installer verifies itself against that checksum before it installs. A checksum that does not match stops the install.

The installer never updates itself. It never fetches a newer version, and there is no self-update path. Upgrading is an explicit operator action: a new tag, a new release, a new checksum, and a fresh install.

## 40.5 ACCEPTANCE

Before an installer or demo release is declared working, a Windows runner must prove:

```text
`install.ps1` completes without elevation and without a schema write
`start-demo.ps1` reaches PostgreSQL, the API, and the console on pinned ports
every released checksum matches the released asset
```

The §31 acceptance gates and the §32 testing requirement remain in force and must stay green. This section adds a packaging gate; it does not replace a gate and does not relax one. A release that passes these checks while §31 or §32 fails is not releasable.

## 40.6 RELEASE AND CI

Two CI obligations are required, and neither is optional:

- Script validation on `windows-latest` for `install.ps1` and `start-demo.ps1`. A script that is not validated on Windows is not shippable.
- A release workflow triggered by a tag push. The tagged release is the only distribution path §40.4 supports. The Windows validation runs in that same workflow, against the tag's own tree, and the release job must not publish unless it passed; a tag push that skips the gate is not releasable.

Release assets are exactly, and the name of the fourth is `SHA256SUMS.txt`:

```text
the source ZIP for the tag
`install.ps1`
`start-demo.ps1`
`SHA256SUMS.txt`
```

## 40.7 BOUNDARY

§40 is packaging and distribution only. It authorizes no fake UI, no placeholder screen, and no mock surface under §24 or §39. It is not a production deployment path, and no script in it may be pointed at a production database.

This section does not relax §24, §30, §31, §32, §33, §38, or §39. Every requirement in those sections remains in force and unchanged. Authorization, default deny, Scope, Audit, capability, Core ownership, the versioned migration boundary, and the design token rules are the same after §40 as before it.

An installer that succeeds and a demo that starts prove only that the software can be obtained and launched. They are not evidence that the architecture is correct. §31 remains the gate for that.

# END MASTER DIRECTIVE
