# Platform Vision

**This document is non-normative.** It is an introduction to the Atlas product
family written for orientation. It is not part of `contract.md` and it decides
nothing.

- It changes no HQ rule and supersedes no contract section.
- It adds no cluster, no plugin, no capability, and no dependency.
- It creates no implementation requirement and no acceptance gate.
- It is not an amendment. Changing any rule still requires a numbered change to
  `contract.md` through the normal council process.

Where this document and `contract.md` disagree, `contract.md` wins without
exception. Where this document and a sibling product's own contract disagree,
that sibling's contract governs its own product and this document is wrong
about the sibling.

`contract.md` § 33 requires nine named documents. Those nine are the required
set; this file is a tenth, descriptive addition, so creating it is a
documentation change and not a contract change.

## The family

Four names are in play, and only three of them are products.

| Name | What it is | Repository | Own contract | Own database |
|---|---|---|---|---|
| **Atlas-HQ** | The HR-centered platform foundation: the Core, the SDK, the boot kernel, and the plugin architecture. | `atlas-hq` | `contract.md` v1.3.1 | `atlas_hq` on PostgreSQL |
| **Atlas-ERP** | An independent general ERP product: item master, purchasing, stock, sales, journals. Not an HR module. | `atlas-erp` | `contract.md` v1.1.1 | `atlas_erp` |
| **Atlas-Ecom** | An independent commerce product: a customer storefront and an `ecom-manager` operator surface. | `atlas-ecom` | `contract.md` v1.1.1 | `atlas_ecom` |
| **Atlas Connect** | A shared protocol specification, vendored as a file into each product. **Not a service, not a hub, not a repository.** | none — `connect/SPEC.md` is copied into the products | `connect/SPEC.md` v1.0.0 | none |

The three products are peers, not a stack. There is no parent, no shared
runtime, and no shared schema.

The rules that follow from that:

- **Every product runs standalone.** Atlas-ERP completes purchasing, stock,
  sale, and journal work with no peer present. Atlas-Ecom completes catalog,
  cart, and checkout with no peer present. Atlas-HQ boots and serves its
  contracts with no peer present.
- **Integration is additive.** Connecting two products adds capability. It
  never becomes a precondition, and a product that has never heard of a peer
  must still be correct on its own.
- **Each product owns its own contract and its own database.** No table is
  shared, read, or joined across a product boundary. Cross-product data is a
  copy under the receiving product's own ownership, not a live view of someone
  else's rows.
- **Connect bridges capabilities, not tables.** A peer advertises a named,
  permission-scoped capability in a manifest; the other side reads a snapshot
  or posts a proposal against it. Authority is explicit per capability
  (`master` / `reader` / `proposer`). The receiving side never issues SQL
  against the peer's database and never writes to a peer's table.

## Where the siblings stand today

This section records what is observable today. **It is not an acceptance
claim.** None of the three products has a completed acceptance gate set, and
this document does not create, waive, or grade one.

Verified by direct inspection on 2026-09-25:

- **Atlas-ERP** is published and clean at `main` `33f6cca` ("feat: apply Atlas
  v1.1.1 tokens to ERP console"), contract v1.1.1.
- **Atlas-Ecom** is published and clean at `main` `e94a6a0` ("feat: apply
  Atlas v1.1.1 tokens to Ecom UI"), contract v1.1.1.
- **Both siblings vendor the same protocol file**, `connect/SPEC.md` v1.0.0,
  byte-identical in intent, authored once and copied.
- **The example dataset is real and shared by id.** Both `db/seed.sql` files
  load the same fictional catalogue: 6 products, 37 colour/size variants, one
  image per variant. The Ecom `product_id` set equals the ERP `item_id` set
  and the `variant_id` sets are equal, so the two catalogues join by identity
  rather than by name or price.
- **A real cross-process smoke exists.** `atlas-erp/tests/cross_process_smoke.py`
  starts a temporary ERP loopback server and runs three Ecom clients against
  it: a read-only manifest/audit read, a connected checkout, and a lower-level
  order smoke. Its last recorded result was a pass over real processes, real
  HTTP, and a real peer database. It is not currently reproducible: the
  temporary PostgreSQL instance it needs has been removed.
- **Both demo UIs are tokenized.** The ERP console and both Ecom pages render
  every colour from the shared token table as CSS custom properties, with an
  explicit light/dark mode and no colour literal outside the token block.

Known limits, stated plainly so nothing here reads as more than it is:

- Almost all domain state in both siblings is **in memory**. The one durable
  table in ERP is `connected_sale_commands` (a connected-sale idempotency
  receipt); the one durable table in Ecom is `connected_orders`. Item master,
  stock, sales, journals, catalog, and cart are process-local and lost on exit.
- The `db/` directories are **example data, not persistence**. No application
  code reads them, and each `db/README.md` deliberately names a database other
  than the product's real one so the two can never be confused.
- Both browser surfaces are **demos**: loopback-only, no authentication, no
  accounts, no audit trail, and one shared cart serving every visitor.
- Each sibling states in its own `PROJECT_STATE.md` that its acceptance gates
  are partial or unmet. That statement still stands.
- The seeds' image URLs were not re-checked for reachability and no licensing
  or attribution review was performed.

## Alignment with existing HQ rules

Nothing below is new. The family already sits inside rules Atlas-HQ has, and
the siblings were built to those shapes rather than to accommodate.

| HQ rule | Section | How the siblings align |
|---|---|---|
| Core → cluster → plugin → module | § 4, and [ARCHITECTURE.md](ARCHITECTURE.md) | Both siblings implement the same four levels with the same vocabulary and the same "no orphan plugins" rule. A cluster is not a plugin; a module is not a contract. |
| SDK-only consumption | § 9, § 23 | HQ plugins import only `atlas_sdk`; Core implements every port. The siblings keep the same one-way dependency direction, which is why a peer is never required to reach inside another product. |
| Contracts, events, outbox | § 10, § 20, § 21 | Communication happens through declared, permission-scoped contracts and through an outbox, never through shared tables. A missing peer is a degraded capability, not a broken system. |
| High connectivity, low coupling | § 36 | The siblings are the largest demonstration of this: they connect across a process and a product boundary while sharing no code, no schema, and no runtime. |
| Standalone-first | § 1, Gate A | Each product builds and runs independently. "Runs without a peer" is a property, not a degraded mode. |
| PostgreSQL as the only database | § 3, § 22 | No sibling introduces a second database technology. |

To be explicit about what is **not** happening:

- **No Atlas-ERP or Atlas-Ecom source is adopted into Atlas-HQ.** Not copied,
  not vendored, not imported, not referenced as an architectural template.
- **No Atlas-ERP or Atlas-Ecom schema is adopted.** No `example_*` or
  `ecom_example` table, column, or constraint enters HQ, and HQ's Core tables
  are untouched by either sibling.
- **No Atlas-ERP or Atlas-Ecom seed is adopted.** The 6-product/37-variant
  dataset stays in the siblings' `db/` directories, read by no application code.
- **No Atlas-ERP or Atlas-Ecom UI code is adopted.** The consoles and the
  storefront are separate files in separate repositories with separate
  dependencies.

This is the direction `contract.md` § 29 already sets: a prior repository is
outside Atlas-HQ, its history is preserved, and its source is not migrated,
copied, depended on, or inspected as an architectural reference. Sibling
products are *more* outside HQ than a prior repository, not less.

## UNRESOLVED — for council, not for this document

These are open questions. **None of them is decided here**, and none may be
treated as decided by the existence of this file.

1. **Canonical token table.** HQ `contract.md` § 39 and the siblings' v1.1.1
   both claim to be the shared reference, and they genuinely disagree:
   - dark `border.control` is `#DFD8C8` in HQ § 39.2 (6.87:1) and `#9AA394` in
     both siblings (3.73:1);
   - light `state.success` is `#2D0000` on `#C7D3C0` in HQ § 39.2 (12.15:1)
     and `#2A7C13` on `#C7D3C0` in both siblings (3.38:1, text use
     restricted);
   - dark `state.danger` is `#6D0808` on `#FFDADA` in HQ and `#2D0000` on
     `#FFDADA` in both siblings;
   - HQ § 39 requires `focus.ring.onAccent` and `state.success.indicator`;
     neither sibling's table has them, and both siblings have a `link.default`
     HQ does not;
   - HQ § 39.2 leaves `fg.muted` with no hex (settled by measurement at use);
     both siblings hard-code `#6A2F2F` / `#B7B3A9`.
   A cross-surface design token cannot have two authorities. This needs one
   canonical table, one owner, and a stated amendment order.
2. **Where Atlas Connect lives.** It is authored once and vendored twice, with
   no canonical home, so drift between copies is possible and undetected today.
   Options are a canonical repository, a vendored file with a verified hash
   check, or a published spec with per-product conformance tests. None is
   chosen.
3. **HR core vs general ERP core.** `contract.md` § 1 scopes HQ as an
   HR-centered platform, while Atlas-ERP is a general ERP with its own item,
   stock, purchasing, and finance model. Whether these are two cores, one core
   plus a product, or two peers with no shared core is undecided. This document
   assumes only that they are peers.
4. **Contract authority order.** When HQ § 39, ERP v1.1.1, Ecom v1.1.1, and
   Connect v1.0.0 all speak to the same subject, which wins, and who arbitrates?
   Undecided. Today each product's own contract governs its own product, which
   is a working default, not a decision.
5. **Python / TypeScript boundary.** HQ and ERP are Python; Ecom is
   TypeScript. The shared vocabulary — manifests, cursors, authority, state
   pairs — is currently maintained by hand in two languages. Whether that
   stays hand-maintained or gains generated bindings is undecided.
6. **Database topology.** Three products, three databases, plus two example
   datasets that must never be mistaken for the real thing. Whether a
   deployment runs one PostgreSQL instance or three, and whether the example
   schemas are ever allowed near a real one, is undecided.
7. **Scope of § 29.** § 29 speaks of "any prior repository". Sibling products
   are currently *not* prior repositories — they are concurrent, independent
   products. Whether siblings are explicitly exempt from § 29's language, or
   whether § 29 needs wording that distinguishes "prior" from "sibling", is
   undecided. Until it is, the conservative reading applies: nothing is
   inspected, copied, or depended on.

## Staged path

Each stage is a decision point. **Nothing beyond the first stage is
authorized, and no stage before the contract amendment touches
`contract.md`.**

1. **Land the current HQ baseline.** Atlas-HQ has a large uncommitted working
   tree: `contract.md` v1.3.1 plus in-progress § 38 and § 39 work. Review and
   commit that baseline first. Until it is committed, nothing else in this
   document is reviewable against a commit.
2. **Take the seven council questions above.** Each is answered in the
   council, not here, and each answer is written down before any code moves.
3. **Amend `contract.md` if — and only if — a decision requires it.** A
   decision that needs a new rule, a new token authority, or a widened § 29 is a
   numbered contract amendment. A decision that needs none of those is
   documentation only. This document cannot make that call.
4. **Only then consider an integration adapter**, and only as a separate,
   explicitly authorized piece of work on top of an amended contract.

The stop line is stage 3. Everything here is orientation for the council;
nothing here authorizes a contract change, a code change, or a merge.

Last updated: 2026-09-25
