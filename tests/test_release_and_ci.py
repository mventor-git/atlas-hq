"""Static checks for the two CI obligations in `contract.md` section 40.6.

Section 40.6 requires script validation on `windows-latest` and a release
workflow triggered by a tag push whose assets are exactly the source ZIP,
`install.ps1`, `start-demo.ps1` and the SHA-256 file. Section 40.3 requires
every listener to bind loopback, and the port `docker-compose.yml` publishes is
one of them.

These read the workflow and compose files as text rather than through a YAML
parser, for two reasons: the project depends on no YAML library, and the key
that matters here is `on`, which YAML 1.1 reads as the boolean `True` - so a
parsed workflow is more awkward to assert against than a read one.

The scope is the shape of the packaging gate, not the platform: section 31
remains the gate for the architecture, and section 40.5's own Windows acceptance
run is a separate concern from the dry run proved here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
COMPOSE = ROOT / "docker-compose.yml"
GATE = ROOT / "tests" / "windows" / "verify_scripts.ps1"
INSTALL_DOC = ROOT / "docs" / "INSTALL.md"
CONTRACT = ROOT / "contract.md"
GITIGNORE = ROOT / ".gitignore"
WEB_MANIFEST = ROOT / "web" / "package.json"
WEB_LOCK = ROOT / "web" / "package-lock.json"

#: The release assets section 40.6 names, and nothing else.
RELEASE_ASSETS = {"atlas-hq-*.zip", "install.ps1", "start-demo.ps1", "SHA256SUMS.txt"}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> str:
    """A PowerShell file as executable source: help blocks and `#` comments removed.

    A sentence that explains why a forbidden thing is forbidden is not the
    forbidden thing, and neither is naming a setting in order to say it is
    deliberately not set. The Windows gate makes the same distinction.
    """
    raw = _text(path)
    without_help = re.sub(r"(?s)<#.*?#>", "", raw)
    return "\n".join(
        line for line in without_help.splitlines() if not re.match(r"\s*#(?!Requires)", line)
    )


def _block(text: str, key: str) -> str:
    """The first line equal to `key`, plus every following line indented under it."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != key:
            continue
        indent = len(line) - len(line.lstrip())
        block = [line]
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            block.append(following)
        return "\n".join(block)
    raise AssertionError(f"no {key!r} block found")


# --- 40.6, first obligation: Windows script validation ------------------------


def test_ci_validates_the_windows_scripts_on_windows_latest() -> None:
    job = _block(_text(CI), "windows-scripts:")

    assert "runs-on: windows-latest" in job
    for script in ("install.ps1", "start-demo.ps1", "tests/windows/verify_scripts.ps1"):
        assert script in job, f"{script} is not validated on Windows"
    # Windows PowerShell 5.1, not PowerShell 7: that is the floor both scripts
    # declare with #Requires, and only 5.1 proves the floor on a real runner.
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File" in job
    assert "pwsh " not in job


def test_the_windows_job_starts_nothing_and_needs_no_secret() -> None:
    job = _block(_text(CI), "windows-scripts:")

    assert "services:" not in job, "the packaging gate gets no database"
    for forbidden in ("secrets.", "docker", "postgres", "npm ci", "pip install"):
        assert forbidden not in job, f"the packaging gate must not use {forbidden}"


def test_the_gate_drives_both_scripts_with_dry_run_only() -> None:
    gate = _text(GATE)

    assert "'-DryRun'" in gate, "the gate drives the scripts with -DryRun"
    assert "-Path $installPath" in gate and "-Path $demoPath" in gate
    assert "install.ps1 -DryRun exits 0" in gate
    assert "start-demo.ps1 -DryRun exits 0" in gate
    assert "no new listener appeared" in gate, "the gate proves it left nothing running"


# --- 40.6 must not have cost the existing gates -------------------------------


def test_ci_keeps_the_postgres_python_and_web_job() -> None:
    job = _block(_text(CI), "test:")

    assert "runs-on: ubuntu-latest" in job
    assert "image: postgres:16" in job
    for step in (
        "ATLAS_TEST_DATABASE_URL",
        "python -m pytest -q",
        "ruff check .",
        "ruff format --check .",
        "pyright",
        "npm ci",
        "npm run typecheck",
        "npm run test",
        "npm run build",
    ):
        assert step in job, f"the PostgreSQL/Python/web job lost {step}"


# --- 40.5/40.6: the tag is gated by the same checks CI runs --------------------


def test_the_release_job_depends_on_the_windows_acceptance_job() -> None:
    # Default deny. A release must not be publishable without proof that the
    # tagged scripts parse and dry-run on Windows, so the dependency is a
    # `needs:` in the workflow, not a convention.
    job = _block(_text(RELEASE), "release:")

    assert "needs: windows-scripts" in job
    # Only the gate may be named: a release that also needs something else would
    # be one more thing to keep green, and this asserts there is nothing else.
    assert re.findall(r"needs: (\S+)", job) == ["windows-scripts"]


def test_the_release_gate_checks_out_the_tag_it_publishes() -> None:
    job = _block(_text(RELEASE), "windows-scripts:")

    assert "runs-on: windows-latest" in job
    # The gate has to read the same tree `git archive` will package.
    assert "ref: ${{ github.ref }}" in job
    for step in (
        "install.ps1",
        "start-demo.ps1",
        "tests/windows/verify_scripts.ps1",
        "[System.Management.Automation.Language.Parser]::ParseFile",
        "powershell -NoProfile -ExecutionPolicy Bypass -File tests\\windows\\verify_scripts.ps1",
        "install.ps1 -SkipChecksum -DryRun",
        "start-demo.ps1 -DryRun",
    ):
        assert step in job, f"the release gate lost {step}"


def test_the_release_gate_holds_no_write_scope_and_needs_no_secret() -> None:
    job = _block(_text(RELEASE), "windows-scripts:")

    assert "contents: write" not in job, "only the release job may write"
    assert "secrets." not in job
    for forbidden in ("services:", "docker", "postgres", "npm ci", "pip install"):
        assert forbidden not in job, f"the release gate must not use {forbidden}"


def test_every_action_in_both_workflows_is_pinned_to_a_major() -> None:
    for workflow in (CI, RELEASE):
        for action in re.findall(r"uses: (\S+)", _text(workflow)):
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", action), (
                f"{action} is not pinned to a major"
            )


# --- 40.4: one name for the checksum asset ------------------------------------


def test_the_contract_names_the_checksum_file_the_release_actually_publishes() -> None:
    text = _text(CONTRACT)
    section_404 = text.split("## 40.4")[1].split("## 40.5")[0]
    section_406 = text.split("## 40.6")[1].split("## 40.7")[0]

    assert "SHA256SUMS.txt" in section_404, "40.4 must name the file the installer looks for"
    assert "`SHA256SUMS.txt`" in section_406, "40.6 must list the exact asset name"
    # A bare `SHA256SUMS` in the asset list is a different filename, and an
    # operator told to download it would find nothing.
    assert "`SHA256SUMS`" not in text, "the asset list must not name a file that does not exist"
    # `[^`]+` so a bare code fence is not read as an asset name.
    assert set(re.findall(r"^`([^`]+)`$", section_406, re.MULTILINE)) == {
        "install.ps1",
        "start-demo.ps1",
        "SHA256SUMS.txt",
    }


def test_the_release_workflow_and_the_docs_use_the_same_checksum_name() -> None:
    assert "SHA256SUMS.txt" in _text(RELEASE)
    assert "SHA256SUMS.txt" in _text(GATE)
    assert "SHA256SUMS.txt" in _text(INSTALL_DOC)
    for document in (RELEASE, GATE, INSTALL_DOC):
        assert not re.search(r"SHA256SUMS(?!\.txt)", _text(document)), (
            f"{document.name} names the checksum file without its extension"
        )


# --- 40.2: the console install runs no unapproved script ----------------------


def test_the_install_path_never_answers_an_npm_prompt() -> None:
    # npm 10 and 11 do not ask; npm 12 does. A yes-answer to a prompt only some
    # versions ask for is a behaviour to depend on nowhere, and the whole point
    # of `--ignore-scripts` plus a named rebuild is that no answer is needed.
    for path in (ROOT / "install.ps1", CI):
        text = _code(path)
        assert "NPM_CONFIG_YES" not in text, f"{path.name} relies on an npm prompt answer"
        assert "npm_config_yes" not in text.lower()


def test_the_only_install_scripts_the_project_approves_are_the_two_it_rebuilds() -> None:
    manifest = json.loads(_text(WEB_MANIFEST))
    approved = {name.rsplit("@", 1)[0] for name in manifest["allowScripts"]}
    lock = json.loads(_text(WEB_LOCK))
    with_install_script = {
        name.removeprefix("node_modules/")
        for name, entry in lock["packages"].items()
        if entry.get("hasInstallScript") and not entry.get("optional")
    }

    assert approved == {"esbuild", "@tailwindcss/oxide"}
    assert with_install_script == approved, (
        f"an unapproved package has an install script: {with_install_script - approved}"
    )
    for path in (ROOT / "install.ps1", CI):
        text = _text(path)
        assert "ci --ignore-scripts" in text or "@('ci', '--ignore-scripts')" in text
        for package in approved:
            assert package in text, f"{path.name} never rebuilds {package}"


def test_the_documented_console_install_is_the_approved_one() -> None:
    # A quickstart that says `npm ci` runs every dependency's install script,
    # which is the one thing 40.2's path exists to prevent, and the quickstart is
    # the first thing an operator following the README types.
    for document in (ROOT / "README.md", ROOT / "web" / "README.md"):
        text = _text(document)
        assert "npm ci --ignore-scripts" in text, (
            f"{document.name} documents no --ignore-scripts install"
        )
        assert "npm rebuild esbuild @tailwindcss/oxide" in text, (
            f"{document.name} documents the install without the named rebuild"
        )
        # Any other `npm ci` in the same document is the bare one, and the
        # lookahead lets the safe line past.
        assert not re.search(r"npm ci(?![^\n]*--ignore-scripts)", text), (
            f"{document.name} still documents a bare `npm ci`"
        )


# --- 40.3: the launcher's loopback rule is a parse ----------------------------


def test_the_launcher_proves_loopback_by_parsing_the_host() -> None:
    code = _code(ROOT / "start-demo.ps1")

    # `^127\.` also accepted `127.0.0.1.example.com`, and .NET's parser accepts
    # the shorthand `127.1` that a URL's resolver would hand to DNS instead. A
    # host that merely looks like an address is a name, so the launcher has to
    # parse the host and ask whether it is a loopback address. The Windows gate
    # proves the behaviour; this is the cheap read that keeps the parse from
    # being quietly replaced by a regex.
    assert "^127" not in code, "loopback is not decided from the text of a host"
    assert "[System.Net.IPAddress]::TryParse" in code
    assert "IsLoopback" in code
    # The one name that always means this machine, and the rule the API applies
    # to its own bind address (tests/test_web_bind_guard.py pins that list).
    assert "'localhost'" in code


def test_the_windows_gate_calls_the_launchers_loopback_check() -> None:
    gate = _text(GATE)

    for marker in (
        "Test-LoopbackHost",
        "127.0.0.1.example.com",
        "[System.Net.IPAddress]::TryParse",
    ):
        assert marker in gate, f"the gate stopped checking {marker}"


# --- 40.3: the DSN's query string cannot redirect the connection ---------------


def test_the_launcher_refuses_a_dsn_query_that_overrides_the_connect_target() -> None:
    code = _code(ROOT / "start-demo.ps1")

    # The gap this closes: the guard read `$parsedDatabaseUrl.Host` and nothing
    # else, while everything after a `?` is a connect-arg to SQLAlchemy and
    # psycopg and a connect-arg wins over the authority. So
    # `...@127.0.0.1:5433/atlas_hq?host=evil.example.com` was read as a loopback
    # URL and connected to evil.example.com. The launcher has to look at the
    # query string as well as the authority.
    assert "$parsedDatabaseUrl.Query" in code, "the query string is never read"
    # A `#` in front of the `?` is the same bypass. .NET puts what follows `#` in
    # `Fragment` and leaves `Query` empty, so a `.Query`-only guard is waved
    # through - while the driver's own parse reads the `?` after it as a query,
    # which `make_url` agrees with. Both halves have to be read.
    assert "$parsedDatabaseUrl.Fragment" in code, "a # can hide a connect-arg"
    # Refused whole rather than key by key: an allowlist of connect-args is one
    # release away from the next one, and a demo DSN needs none of them. The
    # names are still in the refusal, because that is the text the operator reads.
    assert "must not carry a query string or a fragment" in code
    for key in ("host", "port", "dbname", "user", "password", "service", "options"):
        assert f"?{key}=" in code, f"the refusal does not name ?{key}= as a connect-arg"
    # The parse-then-judge order is what makes the guard mean anything, and the
    # host check stays: a tail-free URL is still judged by the loopback rule.
    assert code.index("$parsedDatabaseUrl.Query") < code.index(
        "Test-LoopbackHost $parsedDatabaseUrl.Host"
    )


def test_the_windows_gate_proves_the_dsn_bypass_and_the_valid_loopback_forms() -> None:
    gate = _text(GATE)

    # The gate drives the launcher itself, because only running it can show what
    # a DSN does: no text scan of the launcher can tell a refused connect-arg
    # from an accepted one.
    for marker in (
        "?host=evil.example.com",
        "?port=6543",
        "?dbname=other&user=other&password=other",
        "?service=pg_service",
        "?options=-c%20statement_timeout=0",
        # The same bypass behind a fragment, and a bare fragment.
        "#f?host=evil.example.com",
        "#?port=6543",
        "#fragment",
        "must not carry a query string or a fragment",
        # The three forms that have to keep working, plus the name that has to
        # keep being refused through the URL and not only through the function.
        "postgresql+psycopg://atlas:atlas@127.0.0.1:5433/atlas_hq",
        "postgresql+psycopg://atlas:atlas@localhost:5433/atlas_hq",
        "postgresql+psycopg://atlas:atlas@[::1]:5433/atlas_hq",
        "postgresql+psycopg://atlas:atlas@127.0.0.1.example.com:5433/atlas_hq",
    ):
        assert marker in gate, f"the gate stopped driving the launcher with {marker}"
    assert "'-DatabaseUrl'" in gate, "the DSN cases go in through the parameter, not a variable"
    assert "-DryRun" in gate, "the DSN cases must not start anything"


# --- 40.2: one install root, and nothing written outside it -------------------


def test_the_installer_writes_every_dependency_under_its_install_root() -> None:
    code = _code(ROOT / "install.ps1")

    # `.venv`, the install stamp and the console's node_modules are the three
    # things an install writes, and 40.2 only allows the install directory. The
    # node_modules directory used to be joined from the *source* root, so
    # `-SourceRoot A -InstallRoot B` wrote a dependency tree into a directory the
    # operator had not named as the install directory - and not where
    # start-demo.ps1 looks for the console.
    roots = set(re.findall(r"\$(?:webPath|venvPath|stampPath) = Join-Path \$(\w+Root)", code))
    assert roots == {"InstallRoot"}, f"a dependency is written under another root: {roots}"


def test_the_installer_refuses_a_source_root_that_is_not_the_install_root() -> None:
    code = _code(ROOT / "install.ps1")

    # Nothing reconciles a split pair, so it is refused rather than half-honoured,
    # and the refusal has to be reachable from the help the operator reads.
    assert "if ($InstallRoot -ne $SourceRoot)" in code
    assert "Stop-Install" in code
    assert "same directory as SourceRoot" in _text(ROOT / "install.ps1"), (
        "the -InstallRoot help has to say the two roots cannot differ"
    )
    gate = _text(GATE)
    assert "-InstallRoot" in gate and "different directories" in gate, (
        "the Windows gate stopped proving the split-root refusal"
    )


# --- 40.3: the tracked set and the log directory -----------------------------


def test_the_tracked_child_cleanup_is_guaranteed_by_the_script() -> None:
    text = _text(ROOT / "start-demo.ps1")

    # One `try` from the first child to the end of the script, and the tracked
    # set stopped in its `finally`. The Windows gate proves the same property
    # against the AST; this is the cheap read that keeps it from being dropped.
    assert "Stop-TrackedChildren" in text
    assert "try {" in text and "} finally {" in text
    assert re.search(r"\$script:Stopped\b", text), "cleanup must be idempotent"
    assert "taskkill" in text, "cleanup stops the tracked tree and nothing else"


def test_logs_are_ignored_and_the_scripts_are_not() -> None:
    patterns = [
        line.strip()
        for line in _text(GITIGNORE).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert "logs/" in patterns, "start-demo.ps1 writes captured child output to logs/"
    for script_ignoring in ("*.ps1", "*.psm1", "*.psd1", "scripts/", "tests/"):
        assert script_ignoring not in patterns, (
            f"{script_ignoring} would hide the release scripts or the gate that checks them"
        )


def test_the_generated_install_stamp_is_ignored() -> None:
    # The gap this closes: install.ps1 writes `.atlas-install-stamp.json` into the
    # install root, and 40.2 makes that the same directory as the source root, so
    # running the installer from a clone leaves a generated file untracked in the
    # repository - where the next `git status` and the next `git add -A` both see
    # it. The name is read out of the installer rather than repeated here, so
    # renaming the stamp cannot quietly leave it tracked again.
    name = re.search(r"\$stampPath = Join-Path \$\w+Root '([^']+)'", _code(ROOT / "install.ps1"))
    assert name, "install.ps1 no longer joins the install stamp to a root"
    patterns = [
        line.strip()
        for line in _text(GITIGNORE).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert name.group(1) in patterns, (
        f"{name.group(1)} is written by an install and is not in .gitignore"
    )
    # Anchored to a path, this pattern would only cover an install root one
    # directory down, and the clone - the case that leaves the file in the tree -
    # writes it at the root. The bare name covers every install root instead.
    assert f"/{name.group(1)}" not in patterns, "the pattern is anchored to a subdirectory"
    # The stamp is generated state. Ignoring it must not also hide the installer
    # that writes it, which is the same release asset the stamp sits beside.
    assert "install.ps1" not in patterns, "ignoring the stamp must not hide install.ps1"


def test_the_release_workflow_runs_only_on_a_version_tag() -> None:
    trigger = [
        line.strip()
        for line in _block(_text(RELEASE), "on:").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    # Exactly this trigger: a `v*` tag push, so no fork can reach the write scope.
    assert trigger == ["on:", "push:", "tags:", "- 'v*'"]


def test_the_release_workflow_holds_only_contents_write() -> None:
    text = _text(RELEASE)

    assert "\npermissions:\n  contents: read\n" in text, "the default is read-only"
    assert "contents: write" in _block(text, "release:"), "the release job needs the write"
    assert set(re.findall(r"contents: (\w+)", text)) == {"read", "write"}
    for scope in ("id-token", "packages", "pull-requests"):
        assert scope not in text, f"{scope} is not needed to publish a release"


def test_the_release_publishes_exactly_the_assets_section_406_names() -> None:
    assets = _block(_text(RELEASE), "files: |").splitlines()[1:]

    assert {line.strip() for line in assets if line.strip()} == RELEASE_ASSETS


def test_the_release_builds_the_bundle_and_a_checksum_that_matches_it() -> None:
    text = _text(RELEASE)

    assert "git archive" in text, "the ZIP is the tag's own tracked tree"
    assert "sha256sum install.ps1 start-demo.ps1" in text
    assert "> SHA256SUMS.txt" in text
    assert "sha256sum --check" in text, "the checksums are proved before the release exists"


def test_the_release_pins_actions_to_a_major_and_prints_no_secret() -> None:
    text = _text(RELEASE)
    actions = re.findall(r"uses: (\S+)", text)

    assert actions, "the release job uses actions"
    for action in actions:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+", action), f"{action} is not pinned to a major"
    assert "secrets." not in text, "the token is the action's to use, never named here"


# --- 40.4: the launcher runs the installer the way its directory is built -----


def test_the_launcher_only_skips_the_checksum_in_a_source_checkout() -> None:
    code = _code(ROOT / "start-demo.ps1")

    # The defect this closes: the launcher ran `install.ps1` with no arguments
    # at all, so a repository clone - which ships no release asset and so has no
    # SHA256SUMS.txt beside the script - was refused by the installer's own
    # 40.4 rule and the demo could not start. The launcher now decides, from the
    # directory it is sitting in, which of the two the install is.
    #
    # Order is the whole guarantee: the checksum file is consulted first, and
    # the switch is granted only on the branch reached when it is absent. A
    # bundle with the file beside it is never even asked whether it looks like a
    # checkout, so a release cannot be talked out of verifying itself.
    assert code.index("SHA256SUMS.txt") < code.index("-SkipChecksum")
    # Appended in exactly one place, and out loud: a silent skip is the thing
    # 40.4 exists to prevent.
    assert code.count("$installArguments += '-SkipChecksum'") == 1
    assert "source checkout: checksum verification skipped" in code
    # A source checkout, read as a whole rather than inferred from one file.
    for marker in ("pyproject.toml", r"src\atlas_core", r"web\package.json"):
        assert marker in code, f"the checkout test no longer looks for {marker}"
    # Default deny: a directory that is neither a bundle nor a checkout is
    # refused before the plan, with both ways out named.
    assert "there is no SHA256SUMS.txt beside this script." in code
    assert "Download install.ps1 and SHA256SUMS.txt from the same release" in code
    assert r"run .\start-demo.ps1 from the repository root" in code


def test_the_launcher_does_not_weaken_the_installer_checksum_rule() -> None:
    launcher = _code(ROOT / "start-demo.ps1")
    installer = _text(ROOT / "install.ps1")

    # -SkipChecksum is install.ps1's own switch and install.ps1's own refusal is
    # what keeps it narrow: a bundle whose bytes do not match is still refused,
    # and the launcher only adds the switch where the file is absent entirely.
    assert "if ($SkipChecksum)" in _code(ROOT / "install.ps1")
    for refusal in (
        "there is no SHA256SUMS.txt beside this installer.",
        "install.ps1 does not match the SHA256SUMS.txt beside it.",
    ):
        assert refusal in installer, f"install.ps1 lost {refusal!r}"
    # The launcher hands the switch over; it never computes or compares a digest
    # itself, so there is no second, weaker rule next to the installer's.
    for forbidden in ("Get-FileHash", "-ine "):
        assert forbidden not in launcher, f"start-demo.ps1 grew {forbidden}"


def test_the_windows_gate_proves_both_of_the_launchers_checksum_branches() -> None:
    gate = _text(GATE)

    # The branch is a property of the directory, so only running the launcher
    # can show it: a text scan cannot tell a checkout from a bundle.
    for marker in (
        "Test-SourceCheckout",
        "source checkout: checksum verification skipped",
        "install.ps1 -SkipChecksum -DryRun",
        "there is no SHA256SUMS.txt beside this script.",
        "run .\\start-demo.ps1 from the repository root",
        # The marker the third case removes to stop being a checkout.
        r"src\atlas_core",
    ):
        assert marker in gate, f"the gate stopped proving {marker}"
    # All three cases are dry runs, so proving the branches starts nothing.
    assert gate.count("Invoke-Script -Path $launchDemo -Arguments @('-DryRun')") == 3


# --- 40.3: the published port is loopback ------------------------------------


def test_compose_publishes_postgres_on_loopback_only() -> None:
    mappings = [
        line.strip().removeprefix("- ").strip('"')
        for line in _text(COMPOSE).splitlines()
        if line.strip().startswith('- "')
    ]

    assert mappings == ["127.0.0.1:5433:5432"], "a bare host:container binds every interface"


def test_the_documented_ports_are_loopback_and_name_the_release_assets() -> None:
    for document in (INSTALL_DOC, ROOT / "README.md"):
        text = _text(document)
        assert "127.0.0.1:5433" in text, f"{document.name} must name the loopback port"
        assert not re.search(r"(?<![\d.])\b5433:5432\b", text), (
            f"{document.name} implies every interface"
        )
    # The operator is told the checksum filename the release actually carries.
    assert "SHA256SUMS.txt" in _text(INSTALL_DOC)


# --- 40.3: a documented DSN names the address, not a name ----------------------

#: The text the release ZIP actually ships: the documents, the two scripts, the
#: compose file, the workflows, and the console's own example environment. Not
#: `contract.md`, which is Plan's wording and not this gate's to police, and not
#: anything under `tests/`, where a `localhost` DSN is the loopback-alias proof.
SHIPPED_TEXT = (
    *(ROOT / "docs").glob("*.md"),
    ROOT / "README.md",
    ROOT / "web" / "README.md",
    ROOT / "web" / ".env.example",
    ROOT / "install.ps1",
    ROOT / "start-demo.ps1",
    ROOT / "docker-compose.yml",
    *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
)

#: A DSN whose authority host is a name instead of an address. `localhost` is
#: loopback by definition, but on Windows it resolves to `::1` first and the
#: published port is IPv4-only, so psycopg waits on a connect that never
#: completes; `[::1]` is the same dead end spelled out. The port is not part of
#: the pattern because the fault is name resolution, which does not care what
#: port the name is attached to.
DSN_HOST_IS_A_NAME = re.compile(r"postgresql\+psycopg://\S*@(?:localhost|\[::1\]):", re.IGNORECASE)


def test_no_shipped_dsn_names_its_host() -> None:
    offenders = []
    for document in SHIPPED_TEXT:
        for match in DSN_HOST_IS_A_NAME.finditer(_text(document)):
            offenders.append(f"{document.relative_to(ROOT)}: {match.group(0)}")

    # `docker-compose.yml` publishes `127.0.0.1:5433` and nothing else, so a
    # shipped DSN that says `localhost` hands the operator a connection that
    # hangs instead of one that is refused. The scripts already refuse a
    # non-loopback *host*; this is the other half, because a name reads as
    # loopback and is not an address.
    assert not offenders, (
        "a shipped DSN resolves a host name, not the loopback address:\n" + "\n".join(offenders)
    )
