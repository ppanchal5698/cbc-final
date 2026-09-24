"""Infisical is wired in without becoming a new way for the stack to die.

Three things are worth pinning, and only one of them is about Infisical.

**Fail-open.** The entrypoint re-execs itself under `infisical run` so secrets
arrive as process environment. That puts a network call on the critical path of
every container start. `set -euo pipefail` is active at that point, so a failed
`infisical login` is one unguarded assignment away from killing the container -
and a secrets manager that takes the whole stack down when it blinks is a worse
outage than the one it prevents. The tests below start the real entrypoint with
a stub CLI that fails, and assert the command still runs.

**Re-exec once.** `exec infisical run -- "$0" "$@"` runs this same script again.
Without the `INFISICAL_INJECTED` guard that is a fork bomb wearing a bow tie.

**A pinned, checksummed CLI.** Infisical's own instructions are `curl ... | bash`.
That binary reads every credential this system owns; it gets a version and a
digest, like anything else that has to be auditable (NFR-3).
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys

import pytest

from tests.shared import ROOT

ENTRYPOINT = ROOT / "infra" / "docker" / "entrypoint.sh"
DOCKERFILE = ROOT / "apps" / "backend" / "Dockerfile"
COMPOSE = ROOT / "infra" / "docker-compose.yml"

# Published in Infisical's own .env.example, and therefore public. A store
# encrypted with it is not encrypted.
PUBLIC_SAMPLE_KEYS = (
    "f13dbc92aaaf86fa7cb0ed8ac3265f47",
    "5lrMXKKWCVocS/uerPsl7V+TX/aaUaI7iDkgl3tSmLE=",
)


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is unavailable here")
    return found


def _stub(directory, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text(body, encoding="utf-8", newline="\n")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


def _run_entrypoint(tmp_path, cli_body: str, **env_extra) -> subprocess.CompletedProcess:
    """Start the real entrypoint with a stubbed `infisical`, echoing a marker.

    `AUTO_BOOTSTRAP=0` skips the Mongo bootstrap; HOME is redirected so the
    trusted-workspace step writes into the tmp dir rather than the developer's
    real ~/.claude.json.
    """
    import sys

    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "infisical", cli_body)
    # The entrypoint shells out to `python`; on Windows that name may not be on
    # PATH inside bash. Point it at the interpreter running these tests.
    _stub(bin_dir, "python", '#!/bin/sh\nexec "{}" "$@"\n'.format(sys.executable))

    env = {
        "PATH": os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")]),
        "HOME": str(tmp_path),
        # Path.home() reads HOME on POSIX and USERPROFILE on Windows; the
        # entrypoint's python step calls it, so both have to point at the tmp
        # dir or this test rewrites the developer's own ~/.claude.json.
        "USERPROFILE": str(tmp_path),
        "AUTO_BOOTSTRAP": "0",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    env.update(env_extra)
    return subprocess.run(
        [_bash(), str(ENTRYPOINT), "echo", "STARTED"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=120,
    )


FAILING_CLI = "#!/bin/sh\nexit 1\n"

WORKING_CLI = """#!/bin/sh
case "$1" in
  login) echo "stub-token" ;;
  run)
    echo "[stub] injected" >&2
    while [ "$1" != "--" ]; do shift; done
    shift
    exec "$@"
    ;;
esac
"""


def test_a_failed_login_does_not_stop_the_container(tmp_path) -> None:
    """`set -e` plus an unguarded assignment is how this breaks."""
    done = _run_entrypoint(
        tmp_path,
        FAILING_CLI,
        INFISICAL_PROJECT_ID="proj-123",
        INFISICAL_UNIVERSAL_AUTH_CLIENT_ID="client-123",
        INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET="shhh",
    )
    assert done.returncode == 0, done.stderr
    assert "STARTED" in done.stdout, "the command never ran; the entrypoint died"
    assert "falling back to .env" in done.stderr


def test_an_unconfigured_stack_is_untouched(tmp_path) -> None:
    """No project id means the pre-Infisical path, with nothing to say about it."""
    done = _run_entrypoint(tmp_path, FAILING_CLI)
    assert done.returncode == 0, done.stderr
    assert "STARTED" in done.stdout
    assert "Infisical" not in done.stderr


def test_secrets_are_injected_and_the_re_exec_happens_once(tmp_path) -> None:
    done = _run_entrypoint(
        tmp_path,
        WORKING_CLI,
        INFISICAL_PROJECT_ID="proj-123",
        INFISICAL_UNIVERSAL_AUTH_CLIENT_ID="client-123",
        INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET="shhh",
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.count("STARTED") == 1
    assert done.stderr.count("[stub] injected") == 1, (
        "the INFISICAL_INJECTED guard did not hold - this re-execs forever"
    )


def test_a_token_alone_is_enough(tmp_path) -> None:
    """Minting the token elsewhere must not require the identity pair too."""
    done = _run_entrypoint(
        tmp_path,
        WORKING_CLI,
        INFISICAL_PROJECT_ID="proj-123",
        INFISICAL_TOKEN="pre-minted",
    )
    assert done.returncode == 0, done.stderr
    assert done.stderr.count("[stub] injected") == 1


def test_the_cli_is_pinned_and_checksummed() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    version = re.search(r"ARG INFISICAL_CLI_VERSION=([0-9][0-9.]*)", dockerfile)
    assert version, "the Infisical CLI version is not pinned"
    for arch in ("AMD64", "ARM64"):
        digest = re.search(
            rf"ARG INFISICAL_CLI_SHA256_{arch}=([0-9a-f]{{64}})", dockerfile
        )
        assert digest, f"no sha256 pinned for {arch}"
    assert "sha256sum -c -" in dockerfile, "the download is never verified"
    assert "setup.deb.sh" not in dockerfile, (
        "that is the unpinned `curl | bash` installer"
    )


def test_the_secret_store_is_not_on_the_app_network() -> None:
    """Postgres and Redis hold the decrypted store; only Infisical reaches them."""
    compose = COMPOSE.read_text(encoding="utf-8")
    for service in ("infisical-db", "infisical-redis"):
        body = compose.split(f"  {service}:", 1)[1].split("\n  infisical")[0]
        assert "- secrets" in body, f"{service} is not on the secrets network"
        assert "- default" not in body, f"{service} is reachable from the app network"


def test_the_infisical_image_is_pinned() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    image = re.search(r"image: infisical/infisical:(\S+)", compose)
    assert image, "the Infisical service has no image"
    assert image.group(1) != "latest", (
        "`latest` on the store holding every credential is an unreviewed upgrade "
        "of the thing guarding them"
    )


def test_the_app_env_file_is_not_fed_to_the_secrets_manager() -> None:
    """Handing ../.env to Infisical would give it every secret it replaces."""
    compose = COMPOSE.read_text(encoding="utf-8")
    body = compose.split("  infisical:", 1)[1].split("\nvolumes:")[0]
    assert "../.env" not in body


def test_no_migrated_key_is_also_set_on_the_web_service() -> None:
    """`web` has no Infisical CLI, so injecting a shared key splits the stack.

    `infisical run` overrides the compose value on platform/worker/parser only.
    Migrating `INTERNAL_API_TOKEN` and `INTERNAL_JWT_SECRET` did exactly that:
    the backend started expecting a credential the frontend was not sending, and
    every server-side render died with `Bearer token required` behind a minified
    React #441. The whole UI, from two lines in an allow-list.

    The shared set is derived from the compose file rather than restated, so a
    key added to `web` later is caught without anyone remembering this.
    """
    yaml = pytest.importorskip("yaml")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import migrate_secrets_to_infisical as migrate
    finally:
        sys.path.pop(0)

    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    services = compose["services"]

    def env_keys(name: str) -> set[str]:
        block = services[name].get("environment") or {}
        return set(block) if isinstance(block, dict) else {
            entry.split("=", 1)[0] for entry in block
        }

    backend: set[str] = set()
    for name in ("platform", "worker", "parser"):
        backend |= env_keys(name)
    shared = env_keys("web") & backend

    clash = sorted(shared & set(migrate.MIGRATE))
    assert not clash, (
        f"{clash} are set on `web` too; injecting them moves only the backend "
        "and 401s every render. They belong in SHARED_WITH_WEB."
    )
    # And the reasons must be on record, not merely absent from MIGRATE.
    assert shared <= set(migrate.SHARED_WITH_WEB) | set(migrate.HOST_SHAPED), (
        f"undocumented web-shared keys: {sorted(shared - set(migrate.SHARED_WITH_WEB) - set(migrate.HOST_SHAPED))}"
    )


def test_the_real_credential_files_are_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in ("infra/infisical.env", "infra/infisical-client.env"):
        assert name in ignored, f"{name} is not gitignored"
        assert (ROOT / f"{name}.example").exists(), f"{name}.example is missing"


def test_infisicals_public_sample_keys_are_not_in_the_repo() -> None:
    """They are in Infisical's published .env.example, so they are public."""
    tracked = subprocess.run(
        ["git", "grep", "-l", "-F", "-e", PUBLIC_SAMPLE_KEYS[0],
         "-e", PUBLIC_SAMPLE_KEYS[1]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode == 128:
        pytest.skip("git is unavailable in this build context")
    hits = [
        line for line in tracked.stdout.splitlines()
        if line and not line.endswith(os.path.basename(__file__))
    ]
    assert not hits, f"Infisical's public sample key is committed in: {hits}"
