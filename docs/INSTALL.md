# Installing and running Atlas-HQ on Windows

`install.ps1` and `start-demo.ps1` are the supported Windows entry points.
`install.ps1` ships as an asset of a tagged GitHub Release; `start-demo.ps1`
is committed in the repository. Both are packaging and distribution surface
around the platform — neither is Core, a Plugin, or a Contract
(`contract.md` §40.1).

For the day-to-day development loop, see
[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md). This document is the first-run
path.

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows PowerShell 5.1 | The edition that ships with Windows. PowerShell 7 also works. |
| Docker Desktop with Compose v2 | Provides PostgreSQL 16 on `127.0.0.1:5433`. |
| Python 3.12 | `uv` provisions it; otherwise the `py` launcher must have it. |
| Node.js 20.19 or newer | Ships `npm`. Only needed for the web console. |
| git | Only needed to build a bundle from a clone. |

## From a release bundle

1. Download the source ZIP and `install.ps1` from the same release, and
   extract the ZIP.
2. Put `SHA256SUMS.txt` from that same release next to `install.ps1`. The
   installer needs it there: it hashes its own bytes and refuses to continue
   unless they match.
3. From the extracted directory:

```powershell
.\install.ps1
```

The first thing the installer does is verify itself. It reads
`SHA256SUMS.txt` beside it, takes the `install.ps1` line out of it, hashes its
own file with SHA-256, and compares the two case-insensitively. A match prints
`SHA-256 verified against SHA256SUMS.txt` and the install continues. A
missing file, a line it cannot read, or a digest that does not match stops the
run before anything is created — there is no flag that turns a mismatch into a
warning.

Then the installer creates `.venv` next to itself, installs this project into
it with its dev extras, and installs the console in `web/`. It then prints the
next command, which is the only thing you need to run:

```powershell
.\start-demo.ps1 -InitializeOperator -OpenBrowser
```

## How the console is installed

Three commands, and no prompt is answered at any point:

```powershell
npm ci --ignore-scripts
npm rebuild esbuild @tailwindcss/oxide
node_modules\.bin\esbuild --version ; node -e "require('@tailwindcss/oxide')"
```

`--ignore-scripts` means no dependency's install script runs while the tree is
installed, so no third-party code executes during an install. The two packages
named in `web/package.json#allowScripts` — and only those two — are then built
by name, and the last command *runs* them: esbuild reports its version, and the
Tailwind oxide addon loads its native binding or throws. If either is missing,
the installer stops with the failing command instead of leaving you a console
that breaks on first use.

Those three commands mean the same thing under npm 10, 11 and 12, which is why
the installer sets no npm configuration: answering a prompt that only some
versions ask for is a behaviour to depend on nowhere. `npm ci` re-uses the
lockfile, so the tree is the one `web/package-lock.json` names either way.

## From a clone

A clone has no `SHA256SUMS.txt` beside the script, because there is no release
asset to check it against, so the clone path says so out loud:

```powershell
.\install.ps1 -SkipChecksum
.\start-demo.ps1 -InitializeOperator -OpenBrowser
```

`-SkipChecksum` is for a source checkout and nothing else. It is the switch
that removes the proof, so never pass it to a file you downloaded: if you
downloaded `install.ps1`, download `SHA256SUMS.txt` from the same release into
the same directory instead and let the installer check itself.

`-InitializeOperator` is required on the first run. The console's development
login answers `503` until an operator principal exists, and this is the command
that creates one. Without the flag the launcher prints the exact
`operator-init` command and writes nothing.

`Ctrl-C` stops the API and the console. PostgreSQL keeps running; stop it
yourself with `docker compose stop postgres`.

## Seeing the plan first

Both scripts answer `-DryRun` by printing every command, every file, and every
environment variable name they would use, and changing nothing:

```powershell
.\install.ps1 -DryRun
.\start-demo.ps1 -DryRun -InitializeOperator
```

`-DryRun` works on a machine that is missing a prerequisite: the missing thing
is reported as a note, and the rest of the plan is still printed. It also works
with no `SHA256SUMS.txt` at all — a dry run prints the verification plan
(the file it would hash, the checksum file it would read) and notes that
nothing was compared, rather than treating the absent file as a failure. The
same is true on a run that fails closed: a real run with a wrong checksum still
stops, but it stops having changed nothing.

A dry run runs nothing, so it verifies nothing. Where a check would have run it
prints the command it would run and says the check was not made; it never
prints a green `[ok]` line for something it did not do, and it ends with
`dry run complete` rather than `installed`.

## What the ports are

| Service | Address | Owner |
|---|---|---|
| PostgreSQL | `127.0.0.1:5433` | the `postgres` service in `docker-compose.yml` |
| Web API | `http://127.0.0.1:8000` | `python -m atlas_web` |
| Web console | `http://127.0.0.1:5175` | `npm run dev` in `web/` |

All three are loopback-only. `start-demo.ps1` refuses to widen a binding, and
refuses a database URL whose host is not loopback, because there is no
`--allow-remote` flag and there is not going to be one. It decides that by
parsing the host as an IP address and asking whether it is a loopback address,
not by matching its text: `127.0.0.1.example.com` starts with an address and is
still somebody else's host, and the rule is the one the API applies to its own
binding below. The API refuses it too,
independently: with `ATLAS_WEB_DEV_LOGIN=1` it will not serve on anything but
loopback and exits with an error instead, because a switch that mints a session
for a fixed principal is only a development convenience while the listener is
reachable from this machine alone.

The query string is refused for the same reason, and it is the other way past
that check. Everything after the `?` is a connect-arg to SQLAlchemy and psycopg —
`?host=`, `?port=`, `?dbname=`, `?user=`, `?password=`, `?service=` and
`?options=` — and a connect-arg wins over the authority, so
`postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq?host=evil.example.com`
reads as a loopback URL and connects to `evil.example.com`. A `#` in front of the
`?` hides nothing: the driver still reads the `?` after it as a query. A local
URL needs none of them, so the launcher refuses any query string or fragment
rather than keeping a list of the keys that redirect.

## Where the database URL comes from

In order: `-DatabaseUrl`, then `ATLAS_DATABASE_URL` from your session, then
`docker compose config`. The last one is the default, and it is how the script
gets the local password without ever writing one into a script. Only
`host:port` is ever printed; the URL itself stays in the child processes'
environment and is never echoed, logged, or written to a file.

## Safety boundaries

Neither script will (`contract.md` §40.2, §40.3, §40.4):

- ask for Administrator elevation, or require it
- read, relax, or change the PowerShell execution policy
- download or run a remote script, including itself
- update itself, or fetch a newer version of anything
- install anything whose own SHA-256 does not match the `SHA256SUMS.txt` beside it
- embed, generate, print, or persist a secret
- write to a production or a remote database
- run `docker compose down`, or remove any volume
- run `operator-init` without an explicit `-InitializeOperator`
- start a listener on anything but `127.0.0.1`
- stop a process it did not start

`install.ps1` writes only inside its install directory plus the user-local npm
cache that npm already owns. Everything it writes — `.venv`, the install stamp
and the console's `node_modules` — goes into the same directory, so
`-SourceRoot` and `-InstallRoot` must resolve to one directory (they both
default to the one the script lives in). A pair that differs is refused:
`-SourceRoot A -InstallRoot B` would have put the console's dependencies in `A`
while the virtual environment went to `B`, which is a write outside the install
directory and is not where `start-demo.ps1` looks for them.
`start-demo.ps1` writes only `logs/` and the child processes' captured output.
Neither migrates a schema: a schema change is delivered by a versioned migration
(`contract.md` §38.15), and the demo's schema work is the application's own on
first run, not the launcher's.

## Logs

`start-demo.ps1` captures each child's output and writes it to `logs/` when that
process exits; a process that dies takes its last twenty lines to the console
with it. Use `-LogRoot <path>` to put them somewhere else. `logs/` is in
`.gitignore`: captured output is not something to commit.

```powershell
Get-Content .\logs\api.out.log -Tail 40
```

The database URL is not in them. It is set per child process and the launcher's
own environment is never modified, so nothing it sets reaches your PowerShell
session or the next one you open.

## Troubleshooting

**`install.ps1 cannot continue: install.ps1 does not match the SHA256SUMS.txt beside it.`**
The two digests are printed underneath: the one the checksum file expects and
the one your copy has. That means your `install.ps1` is not the file the
release was tested against — a truncated download, an editor that rewrote it,
or a different release's asset. Re-download `install.ps1` and `SHA256SUMS.txt`
from the same release into the same directory and check again. Do not work
around it with `-SkipChecksum`.

**`install.ps1 cannot continue: there is no SHA256SUMS.txt beside this installer.`**
The checksum file is a release asset, so it is not in your download folder or
not next to the script. Download it from the same release and put the two files
in one directory. From a repository clone, where there is no release asset, use
`-SkipChecksum` instead.

**`install.ps1 cannot continue: SHA256SUMS.txt has no readable 'install.ps1' line.`**
The file is there but is not in `sha256sum` format — 64 hex characters, a
space, then the file name — or it lists other files only. Download
`SHA256SUMS.txt` again; if it still fails to parse, the asset is not the one
this release was tested against.

**`install.ps1 cannot continue: one or more prerequisites are not met.`**
The unmet ones are listed, one per line. Each names the tool to install.

**`install.ps1 cannot continue: the install directory and the source directory are different directories.`**
`-SourceRoot` and `-InstallRoot` were given two different paths. Everything the
installer writes has to go into the one install directory, so the pair is
refused before anything is created. Drop `-InstallRoot`, or point `-SourceRoot`
at the directory you want installed into. A dry run refuses it too, so
`-DryRun` shows you which of the two you changed.

**`port 8000 is already in use by <name> (pid <n>)`**
Free the port and re-run. The launcher names the owner rather than killing it:
it stops only what it started.

**`the database host is <host>, which is not loopback`**
`ATLAS_DATABASE_URL` in your session points somewhere else. Either unset it so
the compose configuration is used, or pass a loopback `-DatabaseUrl`.

**`operator-init failed with exit code 2`**
That is a refusal, not a crash, and the message above it is the reason. The
common one is a database that is not reachable yet — check
`docker compose ps`. Re-running the same command is safe; it is idempotent.

**The console loads but the API answers 503**
`-InitializeOperator` was not passed, so no principal exists. Stop the launcher
and start it again with the flag.

**`npm asks before running a dependency's install scripts`**
You are running `npm ci` by hand. Use `npm ci --ignore-scripts` and then
`npm rebuild esbuild @tailwindcss/oxide` instead; those are the two commands
`install.ps1` runs, and they ask nothing on npm 10, 11 or 12.

**`install.ps1 cannot continue: the approved console build did not produce ...`**
`npm ci --ignore-scripts` ran but the named rebuild did not produce esbuild's
binary. Delete `web\node_modules` and run the installer again — a partial
`node_modules` is not repairable in place — or re-run with `-SkipWeb` to install
the backend only.

**`refusing to serve the development login on '0.0.0.0'`**
`ATLAS_WEB_DEV_LOGIN=1` is set and `python -m atlas_web` was asked to bind a
routable address. Bind `127.0.0.1`, or unset `ATLAS_WEB_DEV_LOGIN`.
`start-demo.ps1` always binds loopback, so it never hits this.

**`Set-ExecutionPolicy` is restricted by policy on this machine**
Neither script changes it. If your policy blocks unsigned local scripts, either
unblock the file (`Unblock-File .\install.ps1`) or run the command it printed
directly: `.venv\Scripts\python.exe -m pip install -e .[dev]`.

## Checking the scripts themselves

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests\windows\verify_scripts.ps1
```

Parses both scripts, checks the parameters and markers `contract.md` §40
requires, scans for the ones it forbids, and runs both in `-DryRun`. It also
copies the installer into a throwaway stub bundle and proves it refuses a
wrong, a malformed and an absent checksum, verifies a right one in either case
or in either `sha256sum` line shape, and honours `-SkipChecksum`. It reads
`web/package.json#allowScripts` and `web/package-lock.json` to prove the
installer's rebuild list is exactly the set of packages that have an install
script, and it walks the PowerShell AST to prove every tracked child is started
inside one `try` whose `finally` calls a `Stop-TrackedChildren` that cannot
throw. It also calls the launcher's own `Test-LoopbackHost`, lifted out of the
file as written, on a table of hosts — so `127.0.0.1.example.com` and `127.1`
are refused by behaviour rather than by a text scan — and proves the installer
refuses a source root and an install root that differ, in a real run and in a
dry run, before any install work. It starts no server, no container, and no
database, and it creates no virtual environment: the runs that must fail closed
are pointed at an install root that is not there or is not the source root.

Last updated: 2026-09-26
