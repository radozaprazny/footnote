"""The deployment (M6 item 3): the revision template agrees with the image and the measured
start, and scripts/deploy.sh creates each resource once, in order, against fake `az` and
`docker`. The real deployment is in PROGRESS.md (Metrics, Deploy)."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from matchlens import cli

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "deploy" / "containerapp.yaml"
DEPLOY = REPO / "scripts" / "deploy.sh"
RUNBOOK = REPO / "docs" / "deploy.md"
# measured at 0.25 vCPU on the devbox (PROGRESS.md, Metrics: Container, Readiness and stop, and
# Container, M5 demo runs)
# longest start to /healthz, 25 Oct: since M5 the runs' replay check computes every overlay
# before the bind (29.9 s on 23 Oct, when the cue timelines were computed after it)
COLD_START_S = 211.8
PROBE_MAX_S = 1.59  # longest /readyz answer during the warm-up
READY_LIMIT_S = int(
    re.search(r"^ready_limit_s=(\d+)", (REPO / "scripts/container.sh").read_text(), re.M)[1]
)


def template():
    return yaml.safe_load(SPEC.read_text())["properties"]["template"]


def probes():
    (container,) = template()["containers"]
    return {p["type"]: p for p in container["probes"]}


def window(probe):
    """How long a probe may fail before it gives up: its first try, then threshold x period."""
    return probe.get("initialDelaySeconds", 0) + probe["periodSeconds"] * probe["failureThreshold"]


def test_the_probes_ask_the_server_on_its_port():
    """Startup and liveness ask /healthz, readiness /readyz, all on the port the image exposes
    and the ingress targets; /readyz on a startup or liveness probe would restart a container
    that is still warming up, and with it the warm-up."""
    dockerfile = (REPO / "Dockerfile").read_text()
    (port,) = map(int, re.findall(r"^EXPOSE (\d+)$", dockerfile, re.M))
    assert re.search(rf"--target-port {port}\b", DEPLOY.read_text())
    paths = {kind: (p["httpGet"]["path"], p["httpGet"]["port"]) for kind, p in probes().items()}
    assert paths == {
        "Startup": ("/healthz", port),
        "Liveness": ("/healthz", port),
        "Readiness": ("/readyz", port),
    }


def test_the_probes_outlast_the_measured_start():
    """Each probe waits longer than the slowest answer measured; the startup probe gives the
    cold start three times its longest, and readiness gives the warm-up at least the window
    container.sh holds a 0.25 vCPU container to (every match streaming within 240 s)."""
    kinds = probes()
    assert min(p["timeoutSeconds"] for p in kinds.values()) >= 2 > PROBE_MAX_S
    assert all(p["timeoutSeconds"] <= p["periodSeconds"] for p in kinds.values())
    assert window(kinds["Startup"]) >= 3 * COLD_START_S
    assert COLD_START_S < READY_LIMIT_S  # container.sh waits that long for /healthz
    assert window(kinds["Readiness"]) >= READY_LIMIT_S == 240
    assert kinds["Readiness"]["successThreshold"] == 1


def test_the_revision_is_the_smallest_always_on_replica():
    """0.25 vCPU with 0.5 GiB (ACA's pairs are 2 GiB a vCPU), one replica always on and at most
    two; a stop gives open streams their graceful timeout before ACA's SIGKILL."""
    tpl = template()
    (container,) = tpl["containers"]
    assert container["resources"] == {"cpu": 0.25, "memory": "0.5Gi"}
    assert tpl["scale"] == {"minReplicas": 1, "maxReplicas": 2}
    assert tpl["terminationGracePeriodSeconds"] > cli.GRACEFUL_TIMEOUT_S


def test_the_template_and_the_script_share_their_names():
    """deploy.sh fills in every placeholder of the template and tags with the template's tags."""
    spec = yaml.safe_load(SPEC.read_text())
    script = DEPLOY.read_text()
    assert set(re.findall(r"\$\{(\w+)\}", SPEC.read_text())) == {"IMAGE", "SUFFIX"}
    (container,) = spec["properties"]["template"]["containers"]
    assert (container["image"], spec["properties"]["template"]["revisionSuffix"]) == (
        "${IMAGE}",
        "${SUFFIX}",
    )
    (tags,) = re.findall(r"^tags=\((.*)\)$", script, re.M)
    assert dict(t.split("=") for t in tags.split()) == spec["tags"]


def render(tag):
    """The template as deploy.sh fills it in (sed's literal replacement)."""
    image = f"acrmatchlens.azurecr.io/matchlens:{tag}"
    return SPEC.read_text().replace("${IMAGE}", image).replace("${SUFFIX}", tag)


@pytest.mark.parametrize("tag", ["5b18038", "1234567", "0123456", "0000000"])
def test_a_sha_of_digits_stays_the_revision_suffix(tag):
    """A short sha of digits only (one commit in 27) or with a leading 0 is still the suffix,
    not a number or an octal one: the placeholders are quoted."""
    tpl = yaml.safe_load(render(tag))["properties"]["template"]
    assert tpl["revisionSuffix"] == tag
    assert tpl["containers"][0]["image"] == f"acrmatchlens.azurecr.io/matchlens:{tag}"


# A fake `az`: a `list` finds what a `create` (or `docker push`, `containerapp update`) made;
# `containerapp create` grants AcrPull as the real CLI does; a call matching $FAKE_FAIL fails;
# a revision's states come from $FAKE_REVISION ("|" between successive answers). Every call goes
# to calls.log; state lives in $FAKE_STATE.
FAKE_AZ = """#!{python}
import json, os, re, sys
from pathlib import Path
import yaml
state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
call = " ".join(args)
with open(state / "calls.log", "a") as f:
    f.write("az " + call + "\\n")
if os.environ.get("FAKE_FAIL") and os.environ["FAKE_FAIL"] in call:
    sys.exit("ERROR: fake failure")
made = json.loads((state / "made.json").read_text())
def opt(name):
    return args[args.index(name) + 1] if name in args else None
def save():
    (state / "made.json").write_text(json.dumps(made))
words = []
for a in args:
    if a.startswith("-"):
        break
    words.append(a)
group, verb = " ".join(words[:-1]), words[-1]
query = opt("--query") or ""
if verb == "login":
    sys.exit(0)
if verb == "create":
    made[group + " " + opt("-n") if group != "role assignment"
         else "role " + opt("--role") + " " + opt("--scope")] = call
    if group == "containerapp" and opt("--registry-identity") == "system":
        made["role AcrPull /id/acrmatchlens"] = "granted by the CLI"
    save()
    sys.exit(0)
if verb == "update":
    tpl = yaml.safe_load(Path(opt("--yaml")).read_text())["properties"]["template"]
    (state / "applied.yaml").write_text(Path(opt("--yaml")).read_text())
    states = os.environ.get("FAKE_REVISION", "Provisioned Running Healthy true").split("|")
    made["revision " + opt("-n") + "--" + tpl["revisionSuffix"]] = states
    save()
    sys.exit(0)
if group == "role assignment":
    print("assignment-1" if "role " + opt("--role") + " " + opt("--scope") in made else "")
    sys.exit(0)
if verb == "list" and group == "acr repository":
    print(int(any(k.startswith("image matchlens:") for k in made)))
    sys.exit(0)
if verb == "show-tags":
    tag = re.search(r"@=='([^']*)'", query)[1]
    print(int("image matchlens:" + tag in made))
    sys.exit(0)
if verb == "list":
    name = re.search(r"name=='([^']*)'", query)[1]
    key = "revision " + name if group == "containerapp revision" else group + " " + name
    print(int(key in made))
    sys.exit(0)
key = ("revision " + opt("--revision") if group == "containerapp revision"
       else group + " " + opt("-n"))
if key not in made:
    sys.exit("ERROR: not found")
answers = {
    "identity.principalId": "principal-1",
    "id": "/id/" + opt("-n"),
    "customerId": "customer-1",
    "properties.configuration.ingress.fqdn": os.environ.get("FAKE_FQDN", "ca-matchlens.example.io"),
}
if query in answers:
    print(answers[query])
elif query.startswith("[properties.provisioningState"):
    states = made[key]
    print("\\n".join(states[0].split()))
    if len(states) > 1:
        made[key] = states[1:]
        save()
"""
# A fake `docker`: a build reads its context from stdin and lists its files, a push makes the
# image.
FAKE_DOCKER = """#!{python}
import io, json, os, sys, tarfile
from pathlib import Path
state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
with open(state / "calls.log", "a") as f:
    f.write("docker " + " ".join(args) + "\\n")
if args[0] == "build":
    assert args[-1] == "-"
    tar = tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()))
    (state / "context.json").write_text(json.dumps([m.name for m in tar if m.isfile()]))
if args[0] == "push":
    made = json.loads((state / "made.json").read_text())
    made["image " + args[1].split("/", 1)[1]] = "pushed"
    (state / "made.json").write_text(json.dumps(made))
"""
# A fake clock: `sleep N` moves it on by N seconds at once, `date +%s` reads it.
FAKE_SLEEP = """#!{python}
import os, sys
from pathlib import Path
clock = Path(os.environ["FAKE_STATE"]) / "clock"
clock.write_text(str(int(clock.read_text()) + int(sys.argv[1])))
"""
FAKE_DATE = """#!{python}
import os, sys
from pathlib import Path
assert sys.argv[1:] == ["+%s"], sys.argv
base = int(os.environ.get("FAKE_NOW", 1_800_000_000))  # 15 Jan 2027, after the freeze
print(base + int((Path(os.environ["FAKE_STATE"]) / "clock").read_text()))
"""
CHANGES = re.compile(r" (create|update|login|build|push) ")
URL = "URL: https://ca-matchlens.example.io/"


@pytest.fixture
def fake(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fakes = {"az": FAKE_AZ, "docker": FAKE_DOCKER, "sleep": FAKE_SLEEP, "date": FAKE_DATE}
    for name, body in fakes.items():
        (bin_dir / name).write_text(body.replace("{python}", sys.executable))
        (bin_dir / name).chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    # the Foundry account exists before the deployment (M3)
    (state / "made.json").write_text(json.dumps({"cognitiveservices account aif-matchlens": ""}))

    def run(**env):
        (state / "calls.log").write_text("")
        (state / "clock").write_text("0")
        result = subprocess.run(
            ["bash", str(DEPLOY)],
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_STATE": str(state),
                **env,
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result, (state / "calls.log").read_text().splitlines()

    run.state = state
    run.clock = lambda: int((state / "clock").read_text())
    return run


def head_tag():
    return subprocess.run(
        ["git", "rev-parse", "--short=7", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def changes(calls):
    return [c for c in calls if CHANGES.search(c + " ")]


def test_a_first_run_creates_everything_in_order_and_a_second_nothing(fake):
    """The first run creates the workspace, the registry, the image (built from the commit's
    files, nothing else), the environment on that workspace, the app pulling with its own
    identity (which the CLI grants AcrPull), Foundry User for that identity, and a revision from
    the template named after the commit; the second run of the same commit only looks."""
    tag = head_tag()
    image = f"acrmatchlens.azurecr.io/matchlens:{tag}"
    result, calls = fake()
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == URL
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    assert result.stdout.splitlines()[0].startswith(f"== commit {tag} on {branch}: ")
    made = changes(calls)
    assert [" ".join(c.split()[:4]) for c in made] == [
        "az monitor log-analytics workspace",
        "az acr create -g",
        "docker build --platform linux/amd64",
        "az acr login -n",
        f"docker push {image}",
        "az containerapp env create",
        "az containerapp create -g",
        "az role assignment create",
        "az containerapp update -g",
    ]
    env_create, app_create, foundry_user = made[5], made[6], made[7]
    assert "--logs-workspace-id customer-1" in env_create and "key" not in env_create
    for flag in (
        f"--image {image}",
        "--registry-identity system",
        "--system-assigned",
        "--ingress external",
        "--environment cae-matchlens",
    ):
        assert flag in app_create
    assert "--role 53ca6127-db72-4b80-b1b0-d745d6d5456d --scope /id/aif-matchlens" in foundry_user
    assert "--assignee-object-id principal-1" in foundry_user
    assert result.stdout.count("already granted") == 1  # AcrPull, by the CLI's create
    assert not [c for c in calls if "acr repository" in c]  # a registry created just now is empty
    (revisions,) = [c for c in calls if c.startswith("az containerapp revision list")]
    assert "--all" in revisions.split()  # inactive revisions too: a suffix is never reused

    applied = yaml.safe_load((fake.state / "applied.yaml").read_text())
    assert applied == yaml.safe_load(render(tag))
    context = json.loads((fake.state / "context.json").read_text())
    committed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.split()
    assert "Dockerfile" in committed and sorted(context) == sorted(committed)
    assert "healthy (waited 0 s)" in result.stdout

    again, calls = fake()
    assert again.returncode == 0, again.stderr
    assert changes(calls) == []
    # the image, the two grants, the revision
    assert sum(ln.startswith("already") for ln in again.stdout.splitlines()) == 4
    assert again.stdout.splitlines()[-1] == URL


def test_a_new_commit_adds_only_its_image_and_revision(fake):
    """On the deployed app, a commit whose image is not in the registry yet is built, pushed and
    deployed as a new revision; nothing else is created."""
    tag = head_tag()
    assert fake()[0].returncode == 0
    made = json.loads((fake.state / "made.json").read_text())
    del made[f"image matchlens:{tag}"], made[f"revision ca-matchlens--{tag}"]
    made["image matchlens:0ld0000"] = "an older commit's"
    (fake.state / "made.json").write_text(json.dumps(made))
    result, calls = fake()
    assert result.returncode == 0, result.stderr
    assert [" ".join(c.split()[:2]) for c in changes(calls)] == [
        "docker build",
        "az acr",  # login
        "docker push",
        "az containerapp",  # update --yaml
    ]
    assert changes(calls)[-1].startswith("az containerapp update")
    assert result.stdout.splitlines()[-1] == URL


@pytest.mark.parametrize(
    "fails",
    [
        "log-analytics workspace list",
        "acr list",
        "acr repository list",
        "acr repository show-tags",
        "containerapp env list",
        "containerapp list",
        "role assignment list",
        "containerapp revision list",
    ],
)
def test_a_failed_lookup_never_passes_for_missing(fake, fails):
    """A lookup that fails (network, throttling) ends the run: it never creates again what is
    there (`az containerapp create` on the live app would put a placeholder image on it)."""
    assert fake()[0].returncode == 0
    result, calls = fake(FAKE_FAIL=fails)
    assert result.returncode != 0
    assert any(fails in c for c in calls)
    assert changes(calls) == []
    assert "URL:" not in result.stdout


@pytest.mark.parametrize("fails", ["acr show", "cognitiveservices account show"])
def test_a_scope_that_cannot_be_looked_up_stops_the_script_before_any_grant(fake, fails):
    """A failed scope lookup ends the run; nothing is granted on an empty scope."""
    result, calls = fake(FAKE_FAIL=fails)
    assert result.returncode != 0
    assert not [c for c in calls if c.startswith("az role assignment")]
    assert "URL:" not in result.stdout


def test_the_script_waits_through_a_revision_warming_up(fake):
    """Activating, then running but not yet ready: the script waits 10 s at a time."""
    result, _ = fake(
        FAKE_REVISION="Provisioning Activating None true|Provisioned Running Unhealthy true"
        "|Provisioned Running Healthy true"
    )
    assert result.returncode == 0, result.stderr
    assert "healthy (waited 20 s)" in result.stdout and fake.clock() == 20
    for line in (
        "0 s: Provisioning Activating None true",
        "10 s: Provisioned Running Unhealthy true",
        "20 s: Provisioned Running Healthy true",
    ):
        assert line in result.stdout.splitlines()
    assert result.stdout.splitlines()[-1] == URL


@pytest.mark.parametrize("ready_after", [60, 61])
def test_the_script_gives_a_revision_600_s(fake, ready_after):
    """Healthy on the poll at 600 s still counts; one poll later the run fails at 600 s."""
    result, _ = fake(
        FAKE_REVISION="|".join(["Provisioned Activating None true"] * ready_after)
        + "|Provisioned Running Healthy true"
    )
    if ready_after == 60:
        assert result.returncode == 0, result.stderr
        assert "healthy (waited 600 s)" in result.stdout
    else:
        assert result.returncode == 1
        assert "not healthy after 600 s" in result.stderr and "URL:" not in result.stdout
    assert fake.clock() == 600


@pytest.mark.parametrize(
    "states",
    [
        "Failed Degraded Unhealthy true",  # provisioning failed
        "Provisioned Failed Unhealthy true",  # the container keeps crashing
    ],
)
def test_a_failed_revision_stops_the_script_at_once(fake, states):
    """A failed revision ends the run at once with its state and the restart command, no URL."""
    result, _ = fake(FAKE_REVISION=states)
    assert result.returncode == 1
    assert f"not healthy after 0 s: {states}" in result.stderr
    assert "az containerapp revision restart" in result.stderr
    assert "URL:" not in result.stdout and fake.clock() == 0


def test_an_inactive_revision_stops_the_script_at_once(fake):
    """Healthy but inactive (an older commit's revision, deployed again): the run ends at once
    and points to the measured way back, a revert deployed; a restart would not make it live."""
    result, _ = fake(FAKE_REVISION="Provisioned Running Healthy false")
    assert result.returncode == 1
    assert "is not active: Provisioned Running Healthy false" in result.stderr
    assert "git revert and deploy" in result.stderr
    assert "restart" not in result.stderr and "activate" not in result.stderr
    assert "URL:" not in result.stdout and fake.clock() == 0


@pytest.mark.parametrize("env", [{"FAKE_FAIL": "ingress.fqdn"}, {"FAKE_FQDN": ""}])
def test_a_missing_ingress_is_no_url(fake, env):
    """A failed or empty FQDN lookup ends the run instead of printing `https:///`."""
    result, _ = fake(**env)
    assert result.returncode != 0
    assert "URL:" not in result.stdout


# The hackathon's Official Rules: the submission closes 27 Oct 2026 11:59 pm Pacific, judging ends
# 10 Nov 11:59 pm
PACIFIC, BRATISLAVA = ZoneInfo("America/Los_Angeles"), ZoneInfo("Europe/Bratislava")
CLOSE = datetime(2026, 10, 27, 23, 59, tzinfo=PACIFIC)
JUDGING_ENDS = datetime(2026, 11, 10, 23, 59, tzinfo=PACIFIC)
FREEZE_FROM, FREEZE_TO = int(CLOSE.timestamp()), int(JUDGING_ENDS.timestamp())


@pytest.mark.parametrize(
    ("now", "frozen"),
    [
        (FREEZE_FROM - 1, False),
        (FREEZE_FROM, True),
        (FREEZE_TO - 1, True),
        (FREEZE_TO, False),
    ],
)
def test_no_deploy_while_the_submission_is_judged(fake, now, frozen):
    """From the submission's close to the judging's end the script refuses before any call
    (Rules 4.8 and 5); a second before and from the end on it deploys."""
    result, calls = fake(FAKE_NOW=str(now))
    if frozen:
        assert result.returncode == 1 and calls == []
        assert re.search(rf"^freeze_from={FREEZE_FROM} ", DEPLOY.read_text(), re.M)
        assert re.search(rf"^freeze_to={FREEZE_TO} ", DEPLOY.read_text(), re.M)
        assert "frozen until 11 Nov 2026 08:59 CET" in result.stderr
        assert "DEPLOY_DURING_JUDGING=yes" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[-1] == URL


@pytest.mark.parametrize(("value", "lets_through"), [("yes", True), ("no", False), ("1", False)])
def test_only_the_owners_yes_lets_a_deploy_through_the_freeze(fake, value, lets_through):
    """DEPLOY_DURING_JUDGING=yes, the owner's decision, lets a deploy through; anything else
    does not."""
    result, calls = fake(FAKE_NOW=str(FREEZE_FROM), DEPLOY_DURING_JUDGING=value)
    if lets_through:
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[-1] == URL
    else:
        assert result.returncode == 1 and calls == []


def test_the_runbook_gives_the_freeze_of_the_script():
    """The runbook's freeze window is the script's, in Bratislava time."""
    freeze = RUNBOOK.read_text().split("## Freeze during judging", 1)[1].split("\n## ", 1)[0]
    freeze = " ".join(freeze.split())  # a date may wrap across a line
    for moment in (CLOSE, JUDGING_ENDS):
        local = moment.astimezone(BRATISLAVA)
        assert local.strftime("%a %-d %b %Y, %H:%M ") + local.tzname() in freeze
    assert "DEPLOY_DURING_JUDGING=yes scripts/deploy.sh" in freeze


def test_the_runbook_tears_down_what_deploy_creates_and_nothing_else():
    """docs/deploy.md's teardown deletes the identity's role assignments first, then the four
    resources deploy.sh creates, the app before its environment, and never the resource group
    or the Foundry account."""
    script = DEPLOY.read_text()
    names = {
        var: re.search(rf"^{var}=(\S+)", script, re.M)[1]
        for var in ("rg", "log", "acr", "env", "app", "foundry")
    }
    text = RUNBOOK.read_text()
    teardown = text.split("## Teardown", 1)[1]
    deletes = [ln for ln in teardown.splitlines() if re.match(r"az .*\bdelete\b", ln)]
    assert deletes[0].startswith("az role assignment delete --ids")
    # only the app identity's assignments: a looser filter would delete the owner's too
    assert """--query "[?principalId=='$principal'].id\"""" in deletes[0]
    assert (
        f"principal=$(az containerapp show -g {names['rg']} -n {names['app']} "
        "--query identity.principalId -o tsv)" in teardown.split(deletes[0])[0]
    )
    assert [re.search(r" -n (\S+)", d)[1] for d in deletes[1:]] == [
        names["app"],
        names["env"],
        names["acr"],
        names["log"],
    ]
    assert all(f"-g {names['rg']} " in d for d in deletes[1:])
    assert "az group delete" not in text
    assert "az role assignment list --all " in deletes[0]  # the assignments at every scope
    assert all(d.endswith("--yes") for d in deletes[1:-1])
    assert deletes[-1].endswith("--yes --force true")  # else its name stays taken 14 days
    (restart,) = [
        ln for ln in text.splitlines() if ln.startswith("az containerapp revision restart")
    ]
    assert "properties.latestReadyRevisionName" in restart  # the revision that serves
    assert not [d for d in deletes if names["foundry"] in d]


def test_the_runbook_names_files_that_exist():
    """Every script, template or doc the runbook names is in the repo."""
    text = RUNBOOK.read_text()
    paths = set(re.findall(r"`((?:scripts|deploy|docs)/[\w./-]+)`", text))
    paths |= set(re.findall(r"^(scripts/\S+)", text, re.M))
    assert {"scripts/deploy.sh", "deploy/containerapp.yaml"} <= paths
    assert [p for p in sorted(paths) if not (REPO / p).exists()] == []


def test_the_runbook_lists_the_resources_deploy_creates():
    """The runbook's table names the script's resources and the Foundry account."""
    script = DEPLOY.read_text()
    names = {re.search(rf"^{v}=(\S+)", script, re.M)[1] for v in ("log", "acr", "env", "app")}
    table = re.findall(r"^\| [^|]+ \| `([\w-]+)` \|", RUNBOOK.read_text(), re.M)
    assert set(table) == names | {re.search(r"^foundry=(\S+)", script, re.M)[1]}


def test_the_url_is_the_same_everywhere():
    """The public URL in the runbook and in PROGRESS.md is one URL."""
    url = re.compile(r"https://ca-matchlens\.[\w.-]+\.azurecontainerapps\.io/")
    urls = {u for path in (RUNBOOK, REPO / "PROGRESS.md") for u in url.findall(path.read_text())}
    assert len(urls) == 1


def test_the_runbook_commands_survive_an_interactive_shell():
    """No `!` inside double quotes in a command: an interactive bash would expand it as history
    and print "event not found" instead of running the pasted line."""
    blocks = re.findall(r"```\n(.*?)```", RUNBOOK.read_text(), re.S)
    lines = [ln for b in blocks for ln in b.splitlines()]
    assert lines and not [ln for ln in lines if re.search(r'"[^"]*![^"]*"', ln)]
