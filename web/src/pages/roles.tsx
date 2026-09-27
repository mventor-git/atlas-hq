import { useEffect, useId, useRef, useState } from "react";

import { ErrorNotice } from "../app/async";
import { PageHeading } from "../app/shell";
import { Alert, EmptyState, Loading } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Checkbox } from "../components/ui/checkbox";
import { Input, Select } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { api, ApiError, type Capability, type GrantState, type Principal, type Role } from "../lib/api";
import { useAsync } from "../lib/useAsync";

/**
 * The grant scopes the API accepts, and which of them this flow can actually use.
 *
 * `scope` carries the organization and the workplace only. A self grant adds a
 * *top-level* `principal_id`; the server refuses a `principal_id` nested inside
 * `scope` with 422 `scope_invalid`, precisely so a client can never believe it
 * made a self grant when it made an organization-wide one. `checkboxBody` is
 * the only place in the console that builds this shape.
 *
 * **Self is not available here, and the option says so.** The server has no
 * self-scope grant read: `GET /principals/{id}/grants` refuses a scope that
 * names no organization or workplace, because the reported scope carries no
 * principal dimension by design. So a self box could only ever be empty-because-
 * nobody-asked, which is the one thing a checkbox must not be. The option is
 * disabled rather than hidden so the reason stays visible, and the writes stay
 * blocked in {@link scopeProblem} as well, so no future change to the picker can
 * quietly start sending them.
 */
const SCOPES = [
  { value: "organization", label: "Organization", available: true },
  { value: "workplace", label: "Workplace", available: true },
  { value: "self", label: "Self (this principal) — not available yet", available: false },
] as const;

/** Why a scope is not offered, in the words the scope field shows. */
export const SELF_SCOPE_UNAVAILABLE =
  "Self (this principal) is not offered here: Core reports no grant state for a principal's own scope, so a " +
  "box could not say whether the grant is held. Use an organization or a workplace scope.";

type ScopeKind = (typeof SCOPES)[number]["value"];

/**
 * The Core-owned capability and actions the management mutations are issued
 * under. They are written down here because they are part of the wire contract,
 * not configuration: a confirmation is bound to the same triple, so a wrong
 * string here is a confirmation the server will refuse to bind to the retry.
 */
const GRANT_CAPABILITY = "authorization.manage";
const CAPABILITY_ACTION = "authorization.capability.set";
const ROLE_ACTION = "authorization.role.set";

export interface GrantTarget {
  principalId: string;
  kind: ScopeKind;
  organizationId: string;
  workplaceId: string;
}

export interface CheckboxBody {
  checked: boolean;
  scope: { organization_id: string | null; workplace_id: string | null };
  /** Top level on purpose. Never inside `scope`. */
  principal_id?: string;
  confirmation_id?: string;
}
export function checkboxBody(
  checked: boolean,
  target: GrantTarget,
  confirmationId?: string,
): CheckboxBody {
  if (target.kind === "self") {
    return {
      checked,
      scope: { organization_id: null, workplace_id: null },
      principal_id: target.principalId,
      confirmation_id: confirmationId,
    };
  }
  return {
    checked,
    scope: {
      organization_id: target.organizationId.trim() || null,
      workplace_id: target.kind === "workplace" ? target.workplaceId.trim() || null : null,
    },
    confirmation_id: confirmationId,
  };
}

/**
 * The read-side scope: the named organization and workplace, and nothing else.
 *
 * A self grant has no readable state, so it names nothing rather than naming the
 * principal. The server refuses an empty scope with 422 `scope_invalid` instead
 * of answering for every scope at once, which is why {@link loadProblem} stops
 * the read before it is sent.
 */
export function scopeQuery(target: GrantTarget): {
  organization_id?: string;
  workplace_id?: string;
} {
  if (target.kind === "self") return {};
  return {
    organization_id: target.organizationId.trim() || undefined,
    workplace_id: target.kind === "workplace" ? target.workplaceId.trim() || undefined : undefined,
  };
}

/** Why the target cannot be sent yet, or null when it can. */
export function scopeProblem(target: GrantTarget): string | null {
  if (!target.principalId.trim()) return "Choose a principal before saving a grant.";
  if (target.kind === "self") {
    // Unreachable from the picker, which disables the option. It is here so that
    // this flow cannot start sending a self grant even if that option is ever
    // re-enabled by mistake.
    return SELF_SCOPE_UNAVAILABLE;
  }
  if (target.kind === "organization" && !target.organizationId.trim()) {
    return "An organization grant needs an organization id.";
  }
  if (target.kind === "workplace" && (!target.organizationId.trim() || !target.workplaceId.trim())) {
    return "A workplace grant needs both an organization id and a workplace id.";
  }
  return null;
}

/** Why grant state cannot be read yet, or null when it can be. */
export function loadProblem(target: GrantTarget): string | null {
  if (!target.principalId.trim()) return "Choose a principal before loading grant state.";
  if (target.kind === "self") {
    return "Core reports no grant state for a principal's own scope, so there is nothing to load.";
  }
  if (target.kind === "organization" && !target.organizationId.trim()) {
    return "An organization scope needs an organization id.";
  }
  if (target.kind === "workplace" && (!target.organizationId.trim() || !target.workplaceId.trim())) {
    return "A workplace scope needs both an organization id and a workplace id.";
  }
  return null;
}

/**
 * One string that names the subject and the scope a piece of state belongs to.
 *
 * Grant state is about one subject in one scope, so this key is what decides
 * whether a report, a confirmation, or a response is still about what is on
 * screen. It is the staleness check, and it has to include every field the reads
 * and the writes use.
 */
export function scopeKey(target: GrantTarget): string {
  return [
    target.principalId.trim(),
    target.kind,
    target.organizationId.trim(),
    target.workplaceId.trim(),
  ].join("|");
}

/** What one checkbox's box and its source label say, as Core reported it. */
export interface CheckSource {
  granted: boolean;
  source: string;
  /** False when nothing has been read yet, so the box may be saying nothing. */
  reported: boolean;
}

const UNREAD: CheckSource = {
  granted: false,
  source: "Not loaded yet",
  reported: false,
};

/**
 * A capability's sources, in words rather than in colour: `direct`, `via role`,
 * both, or nothing. A capability a role provides is *effective* without being
 * *direct*, which is exactly the case a view has to explain — unticking the box
 * removed the grant but not the permission.
 */
export function capabilitySource(grants: GrantState | null, capabilityId: string): CheckSource {
  if (!grants) return UNREAD;
  const entry = grants.capabilities.find((item) => item.capability_id === capabilityId);
  if (!entry) return { granted: false, source: "Not reported by Core", reported: true };
  const viaRole = entry.role_ids.length > 0;
  if (entry.direct && viaRole) {
    return { granted: true, source: `direct and via role ${entry.role_ids.join(", ")}`, reported: true };
  }
  if (entry.direct) return { granted: true, source: "direct", reported: true };
  if (viaRole) {
    return { granted: true, source: `via role ${entry.role_ids.join(", ")}`, reported: true };
  }
  return { granted: false, source: "not granted", reported: true };
}

/** A role's state. An unheld role still gets a checkbox. */
export function roleSource(grants: GrantState | null, roleId: string): CheckSource {
  if (!grants) return UNREAD;
  const entry = grants.roles.find((item) => item.role_id === roleId);
  if (!entry) return { granted: false, source: "Not reported by Core", reported: true };
  return entry.assigned
    ? { granted: true, source: "assigned", reported: true }
    : { granted: false, source: "not assigned", reported: true };
}

/** The one refusal that becomes a question instead of a rollback. */
export function needsConfirmation(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.code === "confirmation_required";
}

export function RolesPage() {
  const [target, setTarget] = useState<GrantTarget>({
    principalId: "",
    kind: "organization",
    organizationId: "",
    workplaceId: "",
  });
  const [grants, setGrants] = useState<GrantState | null>(null);
  const [grantsError, setGrantsError] = useState<unknown>(null);
  const [loadingGrants, setLoadingGrants] = useState(false);

  const capabilities = useAsync(() => api.capabilities(), []);
  const roles = useAsync(() => api.roles(), []);
  const principals = useAsync(() => api.principals(), []);

  const loadBlock = loadProblem(target);
  // A box may only be ticked when the box's own meaning is known, which means the
  // state for this exact subject and scope has been read: an empty box then says
  // "Core reports nothing held" rather than "nobody asked yet".
  const blockReason = scopeProblem(target) ?? (grants ? null : "Load the grant state before changing it.");

  /**
   * The key of what is on screen, kept in a ref so a response can be compared
   * against the selection that exists *now* rather than the one it was sent for.
   * A read that answers after the operator has moved on is stale, and a stale
   * report is the one thing this page must never show against the wrong target.
   */
  const targetKey = scopeKey(target);
  const shownKey = useRef(targetKey);
  shownKey.current = targetKey;
  /** Monotonic ticket: only the newest read may write, or clear the busy flag. */
  const loadTicket = useRef(0);

  async function loadGrants(at: GrantTarget = target) {
    const ticket = ++loadTicket.current;
    const key = scopeKey(at);
    setLoadingGrants(true);
    setGrantsError(null);
    try {
      const next = await api.grants(at.principalId.trim(), scopeQuery(at));
      if (stale(ticket, key)) return;
      setGrants(next);
    } catch (error) {
      if (stale(ticket, key)) return;
      // Nothing is left over from a previous subject: an empty list that belongs
      // to someone else is worse than no list.
      setGrants(null);
      setGrantsError(error);
    } finally {
      // Only the newest read may report the region idle; an older one landing
      // late must not clear the flag while a newer read is still in flight.
      if (ticket === loadTicket.current) setLoadingGrants(false);
    }
  }

  /** True when a read answers for something the page has already moved off. */
  function stale(ticket: number, key: string): boolean {
    return ticket !== loadTicket.current || key !== shownKey.current;
  }

  /**
   * Any change to the subject or the scope retires the current report, and
   * retires every read still in flight: a late answer for the old target is
   * discarded rather than drawn against the new one.
   */
  function select(next: GrantTarget) {
    setTarget(next);
    setGrants(null);
    loadTicket.current += 1;
    setLoadingGrants(false);
  }

  /** Re-read after a save, so the summary and the sources are the server's. */
  function refresh() {
    if (target.kind === "self") return;
    void loadGrants();
  }

  return (
    <>
      <PageHeading
        title="Roles"
        lead="Grant and revoke capabilities and roles for a principal. Every box is a real Core decision: the server rechecks authorization, principal activity, and registration on both the grant and the revoke, so a tick never changes anything on its own."
      />

      {/* The whole page body is the grant-loading region: a read in flight makes
          every box and the summary provisional, and a screen reader is told so
          rather than left to read a report that is about to be replaced. */}
      <div className="flex flex-col gap-4" aria-busy={loadingGrants}>
        <Card>
          <CardHeader>
            <CardTitle>Subject and scope</CardTitle>
            <CardDescription>
              The subject comes from <code className="font-mono text-xs">GET /api/principals</code>, which
              Core authorizes exactly as it does the other catalogues. The id can still be typed and verified
              against{" "}
              <code className="font-mono text-xs">GET /api/principals/&#123;id&#125;/grants</code>; an
              unknown id answers 404.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <PrincipalPicker
              target={target}
              onChange={select}
              state={principals.data?.principals ?? null}
              loading={principals.loading}
            />
            <SubjectField target={target} onChange={select} />
            <ScopeKindField target={target} onChange={select} />
            <OrganizationField target={target} onChange={select} />
            <WorkplaceField target={target} onChange={select} />
          </CardContent>
          {principals.error ? (
            <div className="px-4 pb-4">
              <ErrorNotice error={principals.error} onRetry={principals.reload} />
            </div>
          ) : null}
          <div className="flex flex-col gap-2 border-t border-border p-4 sm:flex-row sm:items-center sm:gap-3">
            <Button
              variant="outline"
              onClick={() => void loadGrants()}
              disabled={loadBlock !== null || loadingGrants}
            >
              {loadingGrants ? "Loading…" : "Load grant state"}
            </Button>
            <p className="text-xs text-muted-foreground">
              The execution scope is always your own. The scope chosen here is what the{" "}
              <em>grant</em> is about.
            </p>
          </div>
          {loadBlock ? (
            <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">{loadBlock}</p>
          ) : null}
        </Card>

        {grantsError ? (
          // A failed read is retryable in place: the same target, the same
          // question, asked again.
          <ErrorNotice error={grantsError} onRetry={() => void loadGrants()} />
        ) : null}
        {grants ? <GrantSummaryCard grants={grants} /> : null}

        {capabilities.error ? <ErrorNotice error={capabilities.error} onRetry={capabilities.reload} /> : null}
        {roles.error ? <ErrorNotice error={roles.error} onRetry={roles.reload} /> : null}

        <CheckboxPanel
          title="Capabilities"
          description="Each tick calls PUT /api/principals/{id}/capabilities/{capability}. The response, not the tick, is what changed."
          loading={capabilities.loading}
          items={capabilities.data?.capabilities ?? null}
          renderItem={(capability) => (
            <CapabilityRow
              key={capability.capability_id}
              capability={capability}
              target={target}
              blockReason={blockReason}
              state={capabilitySource(grants, capability.capability_id)}
              onSaved={refresh}
            />
          )}
          emptyTitle="No capabilities are registered"
        />

        <CheckboxPanel
          title="Roles"
          description="Each tick calls PUT /api/principals/{id}/roles/{role}. A role carries the capabilities it declares."
          loading={roles.loading}
          items={roles.data?.roles ?? null}
          renderItem={(role) => (
            <RoleRow
              key={role.role_id}
              role={role}
              target={target}
              blockReason={blockReason}
              state={roleSource(grants, role.role_id)}
              onSaved={refresh}
            />
          )}
          emptyTitle="No roles are registered"
        />
      </div>
    </>
  );
}

// --- fields ----------------------------------------------------------------

interface FieldProps {
  target: GrantTarget;
  onChange: (target: GrantTarget) => void;
}

function SubjectField({ target, onChange }: FieldProps) {
  const id = useId();
  return (
    <div>
      <Label htmlFor={`${id}-principal`}>Principal id</Label>
      <Input
        id={`${id}-principal`}
        value={target.principalId}
        onChange={(event) => onChange({ ...target, principalId: event.target.value })}
        placeholder="atlas.local.operator"
        autoComplete="off"
        spellCheck={false}
        className="mt-1"
      />
    </div>
  );
}

/**
 * The subject picker, over the directory Core returned.
 *
 * A native `<select>` with a real `<label>`, so it is reachable and announced
 * without a custom listbox. An inactive principal is marked in words rather than
 * by styling alone (§39.3), and a typed id that is not in the directory still
 * shows as no selection — the `Principal id` field beside it stays the fallback.
 */
function PrincipalPicker({
  target,
  onChange,
  state,
  loading,
}: FieldProps & { state: Principal[] | null; loading: boolean }) {
  const id = useId();
  const listed = state?.some((item) => item.principal_id === target.principalId) ?? false;
  return (
    <div>
      <Label htmlFor={`${id}-picker`}>Principal</Label>
      <Select
        id={`${id}-picker`}
        value={listed ? target.principalId : ""}
        disabled={loading}
        onChange={(event) => onChange({ ...target, principalId: event.target.value })}
        className="mt-1"
      >
        <option value="">{loading ? "Loading principals…" : "Choose a principal"}</option>
        {state?.map((item) => (
          <option key={item.principal_id} value={item.principal_id}>
            {item.display_name ? `${item.display_name} — ${item.principal_id}` : item.principal_id}
            {item.active ? "" : " (inactive)"}
          </option>
        ))}
      </Select>
    </div>
  )
}

/**
 * The grant scope, with every scope the API accepts listed — including the one
 * this flow cannot use. Hiding it would make its absence unexplained; the option
 * carries `disabled` and says "not available yet" in the label itself, and the
 * reason is in the note below, wired to the control with `aria-describedby` so
 * it is announced with the scope rather than only drawn under it.
 */
function ScopeKindField({ target, onChange }: FieldProps) {
  const id = useId();
  const noteId = `${id}-kind-note`;
  return (
    <div>
      <Label htmlFor={`${id}-kind`}>Grant scope</Label>
      <Select
        id={`${id}-kind`}
        value={target.kind}
        aria-describedby={noteId}
        onChange={(event) => onChange({ ...target, kind: event.target.value as ScopeKind })}
        className="mt-1"
      >
        {SCOPES.map((scope) => (
          <option key={scope.value} value={scope.value} disabled={!scope.available}>
            {scope.label}
          </option>
        ))}
      </Select>
      <p id={noteId} className="mt-1 text-xs text-muted-foreground">
        {SELF_SCOPE_UNAVAILABLE}
      </p>
    </div>
  );
}

function OrganizationField({ target, onChange }: FieldProps) {
  const id = useId();
  const needed = target.kind !== "self";
  return (
    <div>
      <Label htmlFor={`${id}-org`}>Organization id</Label>
      <Input
        id={`${id}-org`}
        value={target.organizationId}
        onChange={(event) => onChange({ ...target, organizationId: event.target.value })}
        placeholder="org-1"
        autoComplete="off"
        disabled={!needed}
        className="mt-1"
      />
      {!needed ? <p className="mt-1 text-xs text-muted-foreground">Not used by a self grant.</p> : null}
    </div>
  );
}

function WorkplaceField({ target, onChange }: FieldProps) {
  const id = useId();
  const needed = target.kind === "workplace";
  return (
    <div>
      <Label htmlFor={`${id}-wp`}>Workplace id</Label>
      <Input
        id={`${id}-wp`}
        value={target.workplaceId}
        onChange={(event) => onChange({ ...target, workplaceId: event.target.value })}
        placeholder="wp-1"
        autoComplete="off"
        disabled={!needed}
        className="mt-1"
      />
      {!needed ? <p className="mt-1 text-xs text-muted-foreground">Only a workplace grant uses this.</p> : null}
    </div>
  );
}

// --- the checkboxes --------------------------------------------------------

/**
 * A list of real checkboxes over one catalogue. The list is a labelled
 * `fieldset` so a screen reader announces the group before the first box, and
 * the checked state shown is the state Core reported, not the state the user last
 * clicked: a save the server refused rolls the box back and says so in words.
 */
function CheckboxPanel<T>({
  title,
  description,
  loading,
  items,
  renderItem,
  emptyTitle,
}: {
  title: string;
  description: string;
  loading: boolean;
  items: T[] | null;
  renderItem: (item: T) => React.ReactNode;
  emptyTitle: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {loading || items === null ? (
          <Loading label={`Loading ${title.toLowerCase()}…`} />
        ) : items.length === 0 ? (
          <EmptyState title={emptyTitle}>Core returned an empty catalogue.</EmptyState>
        ) : (
          <fieldset>
            <legend className="sr-only">{title} for the selected subject and scope</legend>
            <ul className="flex flex-col divide-y divide-border">
              {items.map((item) => (
                <li key={itemKey(item)} className="py-2">
                  {renderItem(item)}
                </li>
              ))}
            </ul>
          </fieldset>
        )}
      </CardContent>
    </Card>
  );
}

function itemKey(item: unknown): string {
  const record = item as { capability_id?: string; role_id?: string };
  return record.capability_id ?? record.role_id ?? String(item);
}

function SaveableRow({
  label,
  id,
  detail,
  target,
  state,
  blockReason,
  action,
  save,
  onSaved,
}: {
  label: string;
  id: string;
  detail: React.ReactNode;
  target: GrantTarget;
  state: CheckSource;
  blockReason: string | null;
  action: string;
  save: (checked: boolean, confirmationId?: string) => Promise<void>;
  onSaved: () => void;
}) {
  const [checked, setChecked] = useState(state.granted);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [reason, setReason] = useState<string | null>(null);
  /** Set when a refusal takes the box away, so focus can be given back to it. */
  const [refocus, setRefocus] = useState(false);
  /** The refused change waiting on a confirmation, or null. */
  const [pending, setPending] = useState<boolean | null>(null);

  const boxRef = useRef<HTMLInputElement>(null);
  const busyRef = useRef(false);
  const detailId = `${id}-detail`;

  /**
   * The subject and scope this row is currently about. A confirmation is bound to
   * the target it was asked about, so when either moves the pending question is
   * dropped rather than left to be answered for a different principal: the
   * server would refuse it as a target mismatch anyway, and a prompt that cannot
   * succeed is worse than no prompt. The saved and refused notices go with it,
   * because both describe a change to something else now.
   */
  const key = scopeKey(target);
  const shownKey = useRef(key);
  shownKey.current = key;

  useEffect(() => {
    setPending(null);
    setSaved(false);
    setReason(null);
    setFailure(null);
    // The optimistic tick goes too. It was about the old target, and a box that
    // is left showing a change nobody made is the same lie as a box that is left
    // showing nothing held — and this render's `state` is already the new
    // target's, because the key moved in the same commit.
    setChecked(state.granted);
    // `state.granted` is deliberately not a dependency: the effect is about the
    // target changing, and the report-sync effect below owns that value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // The box follows what Core reported. A save in flight owns the box until the
  // server has answered, so a report landing mid-save cannot overrule it.
  useEffect(() => {
    if (!busyRef.current) setChecked(state.granted);
  }, [state.granted]);

  // After the render that re-enabled it, because focusing a disabled input does
  // nothing at all.
  useEffect(() => {
    if (!refocus) return;
    setRefocus(false);
    boxRef.current?.focus();
  }, [refocus]);

  function start() {
    busyRef.current = true;
    setBusy(true);
    setSaved(false);
    setReason(null);
    setFailure(null);
  }

  function stop() {
    busyRef.current = false;
    setBusy(false);
  }

  /** True once the subject or scope has moved on from what `key` names. */
  function movedOn(): boolean {
    return shownKey.current !== key;
  }

  async function onChange(next: boolean) {
    // Optimistic, and the server is what decides: every refusal below rolls the
    // box back to what Core still believes.
    setChecked(next);
    start();
    try {
      await save(next);
      // The answer is about the subject and scope this click named. If either
      // moved while the request was in flight, this row is now somebody else's
      // and the result belongs to neither of them.
      if (movedOn()) return;
      setPending(null);
      setSaved(true);
      onSaved();
    } catch (error) {
      if (movedOn()) return;
      if (needsConfirmation(error)) {
        // A confirmation-required policy is a question, not a verdict. The box
        // stays where the user put it while the question is open, and only the
        // answer moves it.
        setPending(next);
        return;
      }
      setChecked(!next);
      setFailure(error);
    } finally {
      stop();
    }
  }

  async function confirmAndRetry() {
    if (pending === null) return;
    const next = pending;
    start();
    try {
      const { confirmation_id } = await api.confirmation({
        capability: GRANT_CAPABILITY,
        action,
        scope: checkboxBody(next, target).scope,
        resource_id: target.principalId.trim(),
      });
      await save(next, confirmation_id);
      if (movedOn()) return;
      setPending(null);
      setSaved(true);
      onSaved();
    } catch (error) {
      // Declined, expired, consumed, or refused again: the box goes back to what
      // Core still believes, and the reason is shown in words.
      if (movedOn()) return;
      setPending(null);
      setChecked(!next);
      setFailure(error);
    } finally {
      stop();
    }
  }

  function decline() {
    if (pending === null) return;
    setChecked(!pending);
    setPending(null);
    setReason("Declined. Nothing was changed.");
    setRefocus(true);
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-start gap-3">
        <Checkbox
          id={id}
          ref={boxRef}
          checked={checked}
          disabled={busy || pending !== null || blockReason !== null}
          aria-describedby={detailId}
          onChange={(event) => void onChange(event.currentTarget.checked)}
        />
        <div className="min-w-0 flex-1">
          <Label htmlFor={id} className="cursor-pointer">
            {label}
          </Label>
          {detail}
          <p id={detailId} className="mt-1 text-xs text-muted-foreground">
            {state.source}
          </p>
        </div>
      </div>
      <p aria-live="polite" className="text-xs text-muted-foreground">
        {busy
          ? "Saving…"
          : saved
            ? "Saved. Core accepted the change."
            : (reason ?? blockReason ?? "")}
      </p>
      {pending !== null ? (
        <ConfirmationPrompt
          capability={GRANT_CAPABILITY}
          action={action}
          subject={label}
          target={target}
          busy={busy}
          onConfirm={() => void confirmAndRetry()}
          onDecline={decline}
        />
      ) : null}
      {failure ? <ErrorNotice error={failure} /> : null}
    </div>
  );
}

/**
 * The question a confirmation-required policy asks, with the three facts the
 * confirmation is bound to — the capability, the action, and the target — spelled
 * out, so a confirmation is never a blind "are you sure". The confirm button
 * takes focus, because the answer is what the user is here to give.
 */
function ConfirmationPrompt({
  capability,
  action,
  subject,
  target,
  busy,
  onConfirm,
  onDecline,
}: {
  capability: string;
  action: string;
  subject: string;
  target: GrantTarget;
  busy: boolean;
  onConfirm: () => void;
  onDecline: () => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => confirmRef.current?.focus(), []);
  const where =
    target.kind === "self"
      ? "this principal only"
      : `${target.organizationId.trim() || "no organization"} / ${target.workplaceId.trim() || "no workplace"}`;

  return (
    <Alert tone="warning" title="This change needs a confirmation">
      <p>
        The roles engine will not change this without a one-time confirmation of the exact change below.
      </p>
      <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-[auto_1fr] sm:gap-x-3">
        <dt className="font-semibold">Capability</dt>
        <dd className="font-mono">{capability}</dd>
        <dt className="font-semibold">Action</dt>
        <dd className="font-mono">{action}</dd>
        <dt className="font-semibold">Target</dt>
        <dd>
          {subject} for <span className="font-mono">{target.principalId.trim()}</span> at {where}
        </dd>
      </dl>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button ref={confirmRef} size="sm" onClick={onConfirm} disabled={busy}>
          Confirm and retry
        </Button>
        <Button size="sm" variant="outline" onClick={onDecline} disabled={busy}>
          Cancel
        </Button>
      </div>
    </Alert>
  );
}

function CapabilityRow({
  capability,
  target,
  state,
  blockReason,
  onSaved,
}: {
  capability: Capability;
  target: GrantTarget;
  state: CheckSource;
  blockReason: string | null;
  onSaved: () => void;
}) {
  const id = useId();
  return (
    <SaveableRow
      id={`${id}-${capability.capability_id}`}
      label={capability.name}
      target={target}
      state={state}
      blockReason={blockReason}
      action={CAPABILITY_ACTION}
      onSaved={onSaved}
      save={async (checked, confirmationId) => {
        await api.setCapability(
          target.principalId.trim(),
          capability.capability_id,
          checkboxBody(checked, target, confirmationId),
        );
      }}
      detail={
        <>
          <p className="font-mono text-xs text-muted-foreground">{capability.capability_id}</p>
          <p className="text-xs text-muted-foreground">
            {capability.kind} &middot; provided by {capability.provider_id}
          </p>
        </>
      }
    />
  );
}

function RoleRow({
  role,
  target,
  state,
  blockReason,
  onSaved,
}: {
  role: Role;
  target: GrantTarget;
  state: CheckSource;
  blockReason: string | null;
  onSaved: () => void;
}) {
  const id = useId();
  return (
    <SaveableRow
      id={`${id}-${role.role_id}`}
      label={role.name}
      target={target}
      state={state}
      blockReason={blockReason}
      action={ROLE_ACTION}
      onSaved={onSaved}
      save={async (checked, confirmationId) => {
        await api.setRole(target.principalId.trim(), role.role_id, checkboxBody(checked, target, confirmationId));
      }}
      detail={
        <>
          <p className="font-mono text-xs text-muted-foreground">{role.role_id}</p>
          {role.capabilities.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1">
              {role.capabilities.map((capability) => (
                <li key={capability}>
                  <Badge tone="neutral">{capability}</Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">This role declares no capabilities.</p>
          )}
        </>
      }
    />
  );
}

/**
 * The effective picture, exactly as Core computed it for the named scope: the
 * capabilities the server enforces, each labelled with the source that grants
 * it, and the roles that are assigned. Empty for a deactivated principal, whose
 * stored state is still reported — a management view has to be able to see what
 * it would be reactivating.
 */
function GrantSummaryCard({ grants }: { grants: GrantState }) {
  const sources = new Map(grants.capabilities.map((item) => [item.capability_id, capabilitySource(grants, item.capability_id)]));
  const direct = grants.capabilities.filter((item) => item.direct).length;
  const viaRole = grants.capabilities.filter((item) => item.role_ids.length > 0).length;
  const assigned = grants.roles.filter((item) => item.assigned).map((item) => item.role_id);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Effective capabilities for {grants.principal_id}</CardTitle>
        <CardDescription>
          Computed by Core for {grants.scope.organization_id ?? "no organization"} /{" "}
          {grants.scope.workplace_id ?? "no workplace"}. The subject appears here as the resource being
          reported on, never as a scope.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-sm">
          {grants.effective_capability_ids.length} effective {grants.effective_capability_ids.length === 1 ? "capability" : "capabilities"}
          {" · "}
          {direct} granted directly
          {" · "}
          {viaRole} granted by a role
          {" · "}
          {assigned.length} {assigned.length === 1 ? "role" : "roles"} assigned
        </p>
        <Table>
          <TableCaption>
            Effective capabilities for {grants.principal_id}, with the source of each one.
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Source</TableHead>
              <TableHead scope="col">Capability</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {grants.effective_capability_ids.length === 0 ? (
              <TableRow>
                <TableCell colSpan={2}>
                  Core reports no effective capabilities for this scope. Stored state is still shown in the
                  checkboxes above.
                </TableCell>
              </TableRow>
            ) : (
              grants.effective_capability_ids.map((capabilityId) => (
                <TableRow key={`effective-${capabilityId}`}>
                  <TableCell>{sources.get(capabilityId)?.source ?? "not reported"}</TableCell>
                  <TableCell className="font-mono text-xs">{capabilityId}</TableCell>
                </TableRow>
              ))
            )}
            {assigned.map((roleId) => (
              <TableRow key={`role-${roleId}`}>
                <TableCell>role</TableCell>
                <TableCell className="font-mono text-xs">{roleId}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
