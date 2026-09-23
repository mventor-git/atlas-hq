# Event Specification

Events carry **what happened**. The guarantee that matters: a business state
change and the event describing it are stored **atomically**, and the event is
delivered **only after commit**.

Authority: `contract.md` §20, §21, §36.

## The two halves of the pipeline

| Object | Responsibility | File |
|---|---|---|
| `OutboxEventPublisher` | writes an envelope **inside** the current transaction | `atlas_core/infrastructure/events/dispatcher.py` |
| `EventDispatcher` | reads **committed** envelopes in a fresh transaction and routes them to in-process subscribers | same file |

```text
plugin calls context.events.publish(event)
        ↓
OutboxEventPublisher.publish()        → uow.outbox.append(envelope)
        ↓                                          (same transaction as the state change)
platform commits  ──────────────────  state + envelope land together
        ↓
EventDispatcher.dispatch_pending()    → uow.outbox.pending(limit)  (fresh session, committed rows only)
        ↓
each envelope → its own transaction → subscribers → mark_dispatched
```

Because the dispatcher re-reads the outbox **after** commit, an envelope from a
rolled-back transaction is invisible to it and is therefore never delivered.

## The shapes

```python
EventId = NewType("EventId", str)          # the id IS the type: "demo.greeted"

@dataclass(frozen=True)
class DomainEvent:
    event_id: EventId                      # stable registry key + logical type
    payload: dict[str, object]
    occurred_at: datetime                  # UTC by default

@dataclass(frozen=True)
class EventEnvelope:                       # the outbox record
    envelope_id: str
    event: DomainEvent
    publisher: str | None                  # plugin id, if known
    created_at: datetime
    dispatched_at: datetime | None         # None ⇒ pending
    attempts: int
    last_error: str | None
```

`envelope.delivered` is `dispatched_at is not None`.

## Publishing

```python
context.events.publish(
    DomainEvent(event_id=EventId("demo.greeted"), payload={...}),
)
```

`publish` builds an `EventEnvelope` and appends it to `uow.outbox` — no I/O of
its own, no separate transaction. The envelope shares the fate of every other
write in the unit of work.

## Dispatching

```python
kernel.dispatcher.dispatch_pending(limit=100)   # returns the count routed
```

Delivery is **at-least-once within one process**: an envelope stays pending
until all its subscribers succeed, so a crash between commit and dispatch
replays it on the next run.

Failure isolation: each envelope is dispatched in its own transaction. A
raising subscriber records the failure (`outbox.record_failure`) and the
envelope is retried next time, while every other envelope still goes out — one
bad subscriber cannot block the bus.

The CLI flushes after rendering a report: `kernel.dispatcher.dispatch_pending()`
in `atlas_hq/cli.py::_run_report`.

## Subscribing

A plugin returns a mapping of **another plugin's published event id** to a
handler:

```python
def bind_subscriptions(self) -> dict[EventId, Callable[[DomainEvent], None]]:
    return {GREETED_EVENT: self._on_greeted}
```

Wired by `Kernel.enable()`; unsubscribed automatically by `Kernel.disable()`
and on enable failure. Duplicate `subscribe()` calls are ignored.

The subscriber registers for the **event id string**. The publisher has no way
to know who is listening; the registry is the only channel. This is the
"Notification Automation may subscribe to events from many Clusters" pattern
from `contract.md` §36.

## Event registry

`EventRegistryPort` (`atlas_sdk/registry.py`), implemented by
`InMemoryEventRegistry`. Publishers and subscribers are indexed **separately** —
a plugin may publish an event it does not subscribe to and vice versa:

| Method | Returns |
|---|---|
| `register_published(event, plugin_id)` / `register_subscribed(...)` | indexed at boot from the manifest |
| `all()` | every seen event id |
| `exists(event_id)` | bool |
| `publishers_of(event_id)` / `subscribers_of(event_id)` | plugin ids |
| `published_by(plugin_id)` / `subscribed_by(plugin_id)` | event ids |

## When event vs query

| | Query | Event |
|---|---|---|
| Question | "what is X **now**?" | "**X happened**" |
| Timing | synchronous, needs an answer now | asynchronous, fire-and-forget |
| Return value | business state | none (subscribers react) |
| Examples | `get_employee`, `list_employees`, `assignments_for`, `policy.evaluate` | `demo.greeted`, `report.generated` |
| SDK surface | `context.people.*`, `context.invoker.invoke` | `context.events.publish`, `context.dispatcher.subscribe` |

Rules (`contract.md` §20):

- Do **not** use events as a universal replacement for queries. If you need an
  answer to continue, query — do not wait on an event round-trip.
- Do **not** use direct table access as a replacement for either.
- Events are published **inside** the transaction; a subscriber never observes
  an event for work that did not happen.

## The broker seam

The seam is `EventPublisherPort` + the subscriber API. A future external broker
replaces `EventDispatcher` behind that seam without touching any publisher —
which is why `contract.md` §21 permits starting without Kafka/RabbitMQ and the
architecture does. No distributed infrastructure is introduced until a real
requirement proves it necessary.

## Outbox storage

The `outbox` table lives in the **same schema as the business tables**
(`atlas_core/infrastructure/persistence/orm.py`, schema `atlas`), on purpose:
an envelope must be stored in the same transaction as the state change it
describes. `attempts >= 0` is a check constraint.

Last updated: 2026-09-23
