# MVENTOR MASTER EXECUTION PROMPT

## Project: ATLAS-HQ — New Platform Foundation

## Status: GREENFIELD / DO NOT CONTINUE ATLAS-BOT

## Priority: ARCHITECTURE FIRST, THEN IMPLEMENTATION

You are not continuing the existing Atlas-bot codebase.

You are starting a **new Atlas generation** from zero.

The existing repository:

`https://github.com/mventor-git/atlas-bot`

must now be treated as **LEGACY / ARCHIVED**.

Do not refactor it.
Do not migrate its architecture.
Do not copy its internal code.
Do not inspect its source code to understand the new architecture.
Do not use it as a technical reference.
Do not assume any old implementation decision remains valid.

The old repository exists only as a historical artifact and must be preserved and archived.

The new project is:

# ATLAS-HQ

Build it as a completely new platform with a new architecture.

---

# 1. THE PRODUCT IDEA

Atlas is no longer:

> "a Telegram bot with HR features."

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

# PostgreSQL as the primary database

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

Use PostgreSQL.

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

Do not carry the old product naming/structure forward.

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

The old Atlas use case around construction daily workforce reporting remains valid as a business use case.

However:

Do not rebuild it as the old Atlas-bot structure.

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

# 29. LEGACY REPOSITORY HANDLING

The current:

`mventor-git/atlas-bot`

must be moved into a clearly archived state.

Important:

Before archiving, preserve its Git history.

Do not delete it.

Do not rewrite its history.

Do not migrate its source into Atlas-HQ.

The new project must not depend on it.

The relationship should become:

```text
atlas-bot
    = LEGACY ARCHIVE

atlas-hq
    = NEW GENERATION
```

You may inspect repository metadata necessary to archive/preserve the repository itself.

You must NOT inspect its source code as an architectural reference for Atlas-HQ.

After archival, treat the old repository as read-only historical material.

---

# 30. ABSOLUTE "DO NOT" LIST

Do not:

```text
continue atlas-bot
refactor atlas-bot
migrate atlas-bot architecture
copy old atlas-bot modules
reuse old database schema by default
assume old naming is correct
hardcode Site into Core
hardcode Telegram into Core
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

Atlas-HQ builds and runs independently from atlas-bot.

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

## Gate M — Authorization

Plugin operations obey Capabilities.

## Gate N — Scope

Plugin data respects Scope.

## Gate O — Composable Reporting

Report Studio consumes at least two different Plugin-provided datasets without changing Report Studio source.

---

# 32. TESTING REQUIREMENT

Every architectural concept must have automated tests.

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

Never solve ambiguity by copying old Atlas-bot architecture.

Never use the legacy codebase as the answer.

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
17. Archive atlas-bot and leave it untouched as legacy.
```

Do not stop after creating empty folders or interfaces.

The foundation must demonstrate actual runtime behavior.

The objective is not to make Atlas-HQ "look modular."

The objective is to make Atlas-HQ **architecturally capable of receiving new business capabilities as Lego pieces without rewriting the Core**.

# END MASTER DIRECTIVE
