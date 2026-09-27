# Atlas-HQ web console

The browser half of Atlas-HQ. React + Vite + TypeScript + Tailwind CSS v4, with
shadcn/ui-style components **copied into this repository and owned by it**
(contract §39.8). The shadcn CLI is not a build step, not a runtime dependency,
and not part of any pipeline here.

## What it talks to

`src/atlas_web`, over `fetch(..., { credentials: "include" })`. The browser
holds exactly one credential: the opaque `atlas_session` cookie, which is
`HttpOnly` and therefore unreadable from JavaScript. There is no token, no
principal in a request body, no capability handle, and no unit of work on this
side. The Core roles engine stays authoritative: nothing here decides, caches,
or predicts a permission.

## Run it

Three steps, in this order. The API is on **8000**, the console on **5175**, and
the operator principal has to exist before the sign-in button can do anything.

**1. Create the local operator** (once per database, from the repository root):

```powershell
$env:ATLAS_DATABASE_URL = "postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq"
.\.venv\Scripts\atlas-hq.exe operator-init `
  --principal atlas.local.operator `
  --organization org_local `
  --create-organization `
  --organization-name "Atlas Local" `
  --grant authorization.manage `
  --grant report.render `
  --grant self.monthly.report.view
```

Both `--principal` and `--organization` are required, and each `--grant` is a
capability you asked for by name — nothing is granted implicitly. Run
`atlas-hq operator-init --help` for the accepted names. Set
`ATLAS_WEB_OPERATOR_PRINCIPAL` to whatever `--principal` you chose.

`--create-organization` is the one flag that writes something you did not name
outright, so it is opt-in and never a default. On a database that already has
`org_local` it does nothing at all: the organization is reused as it is, and a
different `--organization-name` will not rename it. On an empty database, without
the flag, the command refuses and prints the exact command to run — it will not
invent an organization id for you. `--organization-name` only means anything
alongside `--create-organization`, and defaults to the `--organization` value.

**2. Start the API** (see `docs/WEB_API.md`):

```powershell
$env:ATLAS_WEB_DEV_LOGIN = "1"
$env:ATLAS_WEB_OPERATOR_PRINCIPAL = "atlas.local.operator"
.\.venv\Scripts\python.exe -m atlas_web --port 8000
```

**3. Start the console**:

```powershell
cd web
npm ci --ignore-scripts
npm rebuild esbuild @tailwindcss/oxide
npm run dev
```

Open **http://127.0.0.1:5175**. The port is pinned with `strictPort`, so if 5175
is busy the dev server fails rather than quietly moving to 5176 and leaving you
staring at a stale bookmark.

The Vite dev server proxies `/api` to `http://127.0.0.1:8000` so the API stays
same-origin: `credentials: "include"` needs no CORS exception and the cookie
keeps `SameSite=Strict`. Point it elsewhere with `ATLAS_WEB_API_URL`.

Those variables are **server** configuration read by `src/atlas_web`,
not by this app. See `.env.example`; there is no secret in any of them.

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Vite dev server on :5175, proxying `/api` to :8000 |
| `npm run build` | `tsc --noEmit` then `vite build` |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run test` | Vitest, once |
| `npm run test:watch` | Vitest, watching |

`npm install` on npm 12 asks before running the `esbuild` and
`@tailwindcss/oxide` postinstall scripts, which fetch their native binaries. So
neither of those scripts runs during the install above: the tree is installed
with `--ignore-scripts` and the two are then built by name, which is the path
CI and [`../install.ps1`](../install.ps1) use. They are first-party build
tooling and are the only two packages approved in
`package.json#allowScripts`, so no prompt is answered anywhere and the commands
mean the same thing under npm 10, 11 and 12.

## Design tokens

`src/index.css` is the **only** file allowed to contain a §39 colour value. It
holds the §39.2 table under the §39.8 variable *names*, with light as the
default and `:root[data-theme="dark"]` as the switch — the attribute
`src/lib/theme.ts` writes. There is no `.dark` class.

| §39.2 token | §39.8 variable | Tailwind colour |
| --- | --- | --- |
| `bg.canvas` | `--background` | `--color-background` |
| `bg.surface` | `--card` | `--color-card` |
| `border.divider` | `--border` | `--color-border` |
| `border.control` | `--input` | `--color-input` |
| `accent.default` | `--primary` | `--color-primary` |
| `onAccent.default` | `--primary-foreground` | `--color-primary-foreground` |
| `fg.default` | `--foreground` | `--color-foreground` |
| `fg.muted` | `--muted-foreground` | `--color-muted-foreground` |
| `focus.ring` | `--ring` | `--color-ring` |
| `focus.ring.onAccent` | `--focus-ring-on-accent` | `--color-ring-on-accent` |
| `state.*` | `--success` / `--success-foreground`, and the same shape for `warning`, `danger`, `info` | matching `--color-*` |
| `state.success.indicator` | `--success-indicator` | `--color-success-indicator` |

Every other file names utilities built from those aliases (`bg-card`,
`border-input`, `text-primary-foreground`, `bg-success`,
`text-success-foreground`) and never a hex (§39.1, §39.3).

A `state.*` pair is two variables that are never separated: the fill is the
bare name and the ink is its `-foreground`, so a component reads both from one
state name and cannot pair an ink with a different fill.

Two roles need their own variable because shadcn has no primitive for them:
`--focus-ring-on-accent` (required on accent-filled controls, because
`focus.ring` on the dark accent fill measures 1.28:1 and is forbidden) and
`--success-indicator` (a non-text pair, never normal-size text).

`--muted-foreground` is deliberately not a §39.2 table cell. It is derived per
theme and had to be settled by measurement, which is what it is: `#785a57` in
light (5.55:1 on canvas, 4.81:1 on surface) and `#e2dcce` in dark (7.13:1 and
5.33:1). The dark ink is *lighter* than `--foreground` because the dark surface
`#52575D` gives `--foreground` only 5.14:1, so lifting away from the surface is
the only way to stay above 4.5:1 there.

### The focus indicator

The base layer in `index.css` owns the whole focus indicator, and **no
component sets an outline colour**. There are exactly two rules:

```css
:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
[data-on-accent]:focus-visible,
[data-on-accent] :focus-visible { outline-color: var(--focus-ring-on-accent); }
```

A control marks itself with `data-on-accent` when it is filled with
`--primary` — the default `Button`, the active nav link, and the skip link do;
`Input`, `Select`, `Checkbox`, and the inactive nav links do not. The accent
rule wins by **specificity** (one extra attribute selector), not by source
order.

This shape exists because the earlier one was wrong: every `Button` variant set
both the plain and the accent outline-colour utility, so equal specificity made
the accent ring win on *every* variant and no control drew the ring its
background called for. Centralising the indicator makes that class of bug
unrepresentable — a call site cannot forget a token, and it cannot override one
either.

### The contrast and focus checks

```powershell
npm run test
```

`src/tokens.test.ts` re-reads `index.css` and:

- asserts each §39.8 variable name exists in both themes and is aliased from
  exactly the `--color-*` the table above names, and that the retired
  Atlas-only names are gone;
- measures every pair §39.5 names, in both themes: body ink, control
  boundaries, on-accent ink, both focus roles, each `state.*` ink on its own
  fill, the success indicator's non-text-only carve-out, and the derived
  `--muted-foreground`;
- asserts the dark `focus.ring`-on-accent pair *fails*, so the
  `focus.ring.onAccent` carve-out stays load-bearing instead of looking
  redundant.

`src/css-output.test.ts` builds the app and reads the **emitted** stylesheet,
because two failure modes are invisible in source: Tailwind silently drops class
names it does not recognise, and CSS selection is decided by specificity rather
than by reading order. It asserts which focus pair is *actually selected* for
the canvas/surface case and the accent case, that the accent rule outranks the
plain one, that exactly one rule assigns an outline colour, and that no stray
ring utility appears.

`src/focus-ring.test.tsx` covers the DOM half: that each `Button` variant is
marked `data-on-accent` if and only if it paints `--primary`.

Two exclusions in `index.css` are load-bearing rather than cosmetic. The
`@source not` directives keep **test files and Markdown** out of Tailwind's
class scan: this README and the focus-ring tests both have to *name* the two
outline-colour utilities in order to assert they are absent, and the scanner
reads any class-name-shaped string from any text file in the tree — so
describing the bug here was enough to make Tailwind emit the very utilities the
bug report says are unused. The tests additionally assemble those names from
fragments at runtime, so the guarantee does not depend on `@source not` behaving
identically across Tailwind versions. And `prefers-reduced-motion` is honoured.

The Python test `tests/test_design_token_contrast.py` owns the §39.2 table
itself and is the authority; this run checks that the frontend still agrees
with it.

## Structure

```
src/
  index.css            the token source (§39.2 -> §39.8) -- the only hex
  index.html           the theme cache read before React mounts
  lib/
    api.ts             the typed client; the only place fetch is called
    errors.ts          one accessible sentence per status
    theme.ts           §39.6 preference + the local mirror
    router.ts          a hash router and page-focus handling
    useAsync.ts        fetch-once, no cache
  components/ui/       owned shadcn-style primitives
  app/                 session context, shell, error notice, sign-in
  pages/               dashboard, roles, reports, self-report
```

## The principal picker

The Roles page offers the subject from `GET /api/principals`, the directory Core
authorizes exactly as it does the capability and role catalogues: a live session
and one Core decision on `authorization.manage` in the caller's own scope. The
response is a directory of `{principal_id, display_name, active}` — a principal's
stored metadata is never on the wire — and the picker states an inactive
principal in words rather than by styling alone.

The `Principal id` field stays beside it: a typed id is still verified against
`GET /api/principals/{id}/grants` (an unknown id answers 404), so a principal
the operator already knows still works if the directory cannot be read.

## The roles flow

Four steps, in this order. Nothing here decides anything; Core does.

1. **Name a subject and a scope.** Organization or workplace. `Self (this
   principal)` is **not offered**: the option is listed and disabled, labelled
   "not available yet", because the server has no self-scope grant read —
   `GET /principals/{id}/grants` refuses a scope that names no organization or
   workplace, and its reported scope carries no principal dimension by design. A
   self box could therefore only ever be empty *because nobody asked*, which is
   the one thing a checkbox must not be. The reason is in words under the scope
   field and wired to the control with `aria-describedby`; the save path blocks a
   self target too, so nothing here can send one.
2. **`Load grant state`.** `GET /api/principals/{id}/grants?organization_id=&workplace_id=`
   hydrates every box. A box is ticked when the capability is a direct grant, is
   carried by a role, or both, and its source is written in words beside it
   (`direct`, `via role <id>`, `direct and via role <id>`). **Until that read,
   the boxes are disabled**: an empty box may mean "nothing is held" but must
   never mean "nobody asked yet". Changing the subject or the scope retires the
   report rather than showing it against the wrong thing — and retires every read
   still in flight, so a slow answer for the previous target is discarded instead
   of drawn against the new one. The whole page body is `aria-busy` while a read
   is outstanding, and a failed read offers a retry in place.
3. **Tick or untick.** The tick is optimistic and the *response* is what changed.
   Any refusal rolls the box back and says why. A successful save re-reads the
   grant state, so the summary and the sources are always the server's.
4. **Confirm when the policy demands it.** A `403 confirmation_required` is a
   question, not a verdict: the page asks `POST /api/confirmations` for a
   one-time confirmation bound to the capability, the action, and the **target**
   principal, then retries the identical change with the `confirmation_id`.
   Declining, an expired confirmation, or an already-consumed one all put the box
   back and name the reason. The prompt spells out the three bound facts and
   takes focus, so a confirmation is never a blind "are you sure". Moving to
   another subject or scope **drops the open question** rather than leaving a
   confirmation for one principal to be answered on another.

The effective summary above the panels is Core's own union, each capability
labelled with the source that grants it — which is what explains why unticking a
box that a role also carries did not remove the permission. It is empty for a
deactivated principal, whose stored state is still shown in the checkboxes.
