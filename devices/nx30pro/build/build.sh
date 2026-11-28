#!/bin/sh
# Build the NX30 Pro firmware candidate from the locked source.
#
# The stages are separated and each one writes its own evidence into
# <artifact-dir>/logs, so a rejected build can be diagnosed from the uploaded
# logs alone and a stage that failed keeps what it produced:
#
#   1. lock gate              check --lock           logs/build-plan.json
#   2. source acquisition     git clone/checkout     logs/source.json
#   3. pre-build verification preflight              logs/preflight.json
#   4. patch/config preflight configure.sh           logs/configure.log
#   5. download               make download          logs/download.log
#   6. compile                make                   logs/build.log
#   7. image inspection       artifacts              logs/artifacts.json
#   8. evidence packaging     publish                build-report.json
#
# Packaging is the last stage and re-reads the evidence, so a build that only
# configured successfully is never published as a candidate. This script never
# flashes anything and never writes to a flash device.
#
# --probe-defconfig stops after stage 4 and publishes probe/final.config plus
# probe/config-audit.json instead of any image: it is the authorized
# `make defconfig` probe that proves the hard gates of a build-blocked lock.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEVICE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$DEVICE_ROOT/../.." && pwd)
HELPER="$SCRIPT_DIR/firmware_lock.py"

LOCK=
SOURCE_DIR=
FEED_DIR=
ARTIFACT_DIR=
JOBS=
CHECK_ONLY=
PROBE=
PINNED_REVISION=

usage() {
	cat <<EOF
Usage: $0 --lock FILE --source-dir DIR --feed-dir DIR --artifact-dir DIR [--check-only] [--probe-defconfig] [--jobs N] [--repo-root DIR]

  --lock FILE         device source lock to build from
  --source-dir DIR    upstream checkout at the locked revision
  --feed-dir DIR      directory that holds the pinned feed checkouts
  --artifact-dir DIR  directory that receives images, evidence, logs and report
  --check-only        validate the lock and print the resolved build plan
  --probe-defconfig   run the authorized \`make defconfig\` probe: stages 1-4 only,
                      publish probe/final.config and probe/config-audit.json,
                      download nothing else, compile nothing, publish no image
  --pinned-revision R source revision the caller pins; it has to equal the lock.
                      Deliberately an argument and not an environment variable:
                      an ambient value must not change what a build refuses to do
  --jobs N            parallelism of the download and the compile stage
  --repo-root DIR     repository root the recorded device patches live in
EOF
}

fail() {
	printf 'Error: %s\n' "$*" >&2
	exit 1
}

while [ "$#" -gt 0 ]; do
	case "$1" in
		--lock)
			[ "$#" -ge 2 ] || fail "--lock requires a value"
			LOCK=$2
			shift 2
			;;
		--source-dir)
			[ "$#" -ge 2 ] || fail "--source-dir requires a value"
			SOURCE_DIR=$2
			shift 2
			;;
		--feed-dir)
			[ "$#" -ge 2 ] || fail "--feed-dir requires a value"
			FEED_DIR=$2
			shift 2
			;;
		--artifact-dir)
			[ "$#" -ge 2 ] || fail "--artifact-dir requires a value"
			ARTIFACT_DIR=$2
			shift 2
			;;
		--jobs)
			[ "$#" -ge 2 ] || fail "--jobs requires a value"
			JOBS=$2
			shift 2
			;;
		--repo-root)
			[ "$#" -ge 2 ] || fail "--repo-root requires a value"
			REPO_ROOT=$2
			shift 2
			;;
		--check-only)
			CHECK_ONLY=1
			shift
			;;
		--probe-defconfig)
			PROBE=1
			shift
			;;
		--pinned-revision)
			[ "$#" -ge 2 ] || fail "--pinned-revision requires a value"
			PINNED_REVISION=$2
			shift 2
			;;
		--help)
			usage
			exit 0
			;;
		*)
			fail "unknown argument: $1"
			;;
	esac
done

[ -n "$LOCK" ] || fail "--lock is required"
[ -f "$LOCK" ] || fail "source lock not found: $LOCK"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
command -v git >/dev/null 2>&1 || fail "git is required"

LOCK=$(CDPATH= cd -- "$(dirname -- "$LOCK")" && pwd)/$(basename -- "$LOCK")

# The probe flags are resolved before any gate so that `--check-only
# --probe-defconfig` can render the plan of a lock that is still build blocked.
PROBE_LOCK_FLAG=
PROBE_CONFIGURE_FLAG=
if [ "$PROBE" = "1" ]; then
	PROBE_LOCK_FLAG=--allow-probe
	PROBE_CONFIGURE_FLAG=--probe
fi

# --check-only resolves the lock and nothing else: no directory is created, no
# source or feed is downloaded and no build is started. A lock that is not
# build ready prints no plan and stops with the build not ready status.
if [ "$CHECK_ONLY" = "1" ]; then
	python3 "$HELPER" check --lock "$LOCK" $PROBE_LOCK_FLAG || exit $?
	exit 0
fi

[ -n "$SOURCE_DIR" ] || fail "--source-dir is required"
[ -n "$FEED_DIR" ] || fail "--feed-dir is required"
[ -n "$ARTIFACT_DIR" ] || fail "--artifact-dir is required"

# A probe publishes evidence, never an image directory: its whole purpose is
# to prove the hard gates of a lock that is still build blocked.
mkdir -p "$ARTIFACT_DIR/logs"
LOGS="$ARTIFACT_DIR/logs"

# Stage 1: the lock gate. Nothing is downloaded before it rendered a plan.
# A probe accepts a lock whose hard gates are still candidates; every other
# structural requirement still applies, and a probe never promotes a package.
PLAN_FILE="$LOGS/build-plan.json"
LOCK_STATUS=0
python3 "$HELPER" check --lock "$LOCK" $PROBE_LOCK_FLAG > "$PLAN_FILE" ||
	LOCK_STATUS=$?
if [ "$LOCK_STATUS" -ne 0 ]; then
	printf 'Error: the source lock is not build ready\n' >&2
	# The status of the lock gate travels to the caller, so a workflow can tell
	# a build blocked lock from any other failure.
	exit "$LOCK_STATUS"
fi

plan_value() {
	python3 - "$PLAN_FILE" "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    plan = json.load(handle)
for key in sys.argv[2].split("."):
    plan = plan[key]
print(plan)
PY
}

SOURCE_REPOSITORY=$(plan_value source_repository)
LOCK_REVISION=$(plan_value source_revision)
PROFILE=$(python3 - "$LOCK" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["target"]["profile"])
PY
)
PATCH_DIR="$REPO_ROOT/$(python3 - "$LOCK" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["device_port"]["patch_layer"])
PY
)"

# The caller may pin the revision as well. When it does, both records have to
# agree, so a stale workflow cannot build another input. The pin is an explicit
# argument: reading it from the environment let a job level variable of the
# workflow leak into every test that ran inside it (probe run 46100893835).
if [ -n "$PINNED_REVISION" ] && [ "$PINNED_REVISION" != "$LOCK_REVISION" ]; then
	fail "the pinned revision $PINNED_REVISION does not match the lock $LOCK_REVISION"
fi

if [ -z "$JOBS" ]; then
	# The runner has four cores and about seven gigabytes of memory. The Go
	# and container builds of this base need more memory than a plain build,
	# so the parallelism stays below the core count.
	JOBS=$(nproc 2>/dev/null || printf '2')
	[ "$JOBS" -gt 3 ] && JOBS=3
fi

# Stage 2: source and feed acquisition at the pinned revisions. A checkout that
# already exists is verified in the next stage instead of being re-created, so
# a result can always be attributed to the pinned commit.
mkdir -p "$SOURCE_DIR" "$FEED_DIR"
if [ ! -d "$SOURCE_DIR/.git" ]; then
	printf 'Cloning the pinned source %s\n' "$LOCK_REVISION"
	git clone --filter=blob:none --no-checkout "$SOURCE_REPOSITORY" "$SOURCE_DIR" >>"$LOGS/source.json.log" 2>&1 ||
		fail "the source could not be cloned"
	git -C "$SOURCE_DIR" checkout --detach "$LOCK_REVISION" >>"$LOGS/source.json.log" 2>&1 ||
		fail "the pinned source revision could not be checked out"
fi

# The feeds are pinned to their commits, so the build input does not drift with
# the moving branches. Every locked feed is mirrored here and the same pin is
# handed to the buildroot through feeds.conf.
python3 - "$LOCK" "$FEED_DIR" "$SOURCE_DIR" <<'PY' || fail "the pinned feeds could not be acquired"
import json
import subprocess
import sys
from pathlib import Path

lock_path, feed_dir, source_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
with open(lock_path, encoding="utf-8") as handle:
    lock = json.load(handle)

lines = []
for feed in lock["feeds"]:
    lines.append(
        "src-git-full %s %s^%s" % (feed["id"], feed["repository"], feed["revision"])
    )
    target = feed_dir / feed["id"]
    if (target / ".git").is_dir():
        continue
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout",
         feed["repository"], str(target)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(target), "checkout", "--detach", feed["revision"]],
        check=True,
    )

(source_dir / "feeds.conf").write_text("\n".join(lines) + "\n", encoding="utf-8")
(feed_dir / "feeds.conf").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

python3 - "$LOCK" "$SOURCE_DIR" "$FEED_DIR" "$JOBS" > "$LOGS/source.json" <<'PY'
import json
import subprocess
import sys


def head(path):
    return subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


lock_path, source_dir, feed_dir, jobs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(lock_path, encoding="utf-8") as handle:
    lock = json.load(handle)
print(json.dumps(
    {
        "source_revision": head(source_dir),
        "locked_revision": lock["source"]["revision"],
        "feeds": {feed["id"]: head("%s/%s" % (feed_dir, feed["id"])) for feed in lock["feeds"]},
        "jobs": int(jobs),
    },
    indent=2,
    sort_keys=True,
))
PY

# Stage 3: the pre-build verification. It refuses a wrong source revision, a
# dirty checkout, the output of an earlier build, a feed that moved and a
# device patch that does not apply, all before anything is downloaded.
python3 "$HELPER" preflight --lock "$LOCK" --source-dir "$SOURCE_DIR" \
	--feed-dir "$FEED_DIR" --repo-root "$REPO_ROOT" --out "$LOGS/preflight.json" \
	$PROBE_LOCK_FLAG > "$LOGS/preflight.stdout" ||
	fail "the pre-build verification failed, nothing was downloaded or compiled"

# The output directory of a build is created only after the lock gate passed, so
# a rejected lock leaves no directory that could be mistaken for a result. A
# probe publishes evidence and never an image directory.
if [ "$PROBE" = "1" ]; then
	mkdir -p "$ARTIFACT_DIR/probe"
else
	mkdir -p "$ARTIFACT_DIR/images"
fi

printf 'Building %s for %s from %s\n' \
	"$(plan_value target.target)/$(plan_value target.subtarget)" \
	"$PROFILE" "$LOCK_REVISION"

# Stage 4: patches, source verifiers, layer merge, `make defconfig`, the audit
# of the FINAL configuration and the overlay secret scan. Nothing compiles here.
CONFIGURE_LOG="$LOGS/configure.log"
CONFIGURE_STATUS=0
sh "$SCRIPT_DIR/configure.sh" --source-dir "$SOURCE_DIR" --lock "$LOCK" \
	--patch-dir "$PATCH_DIR" --log-dir "$LOGS" $PROBE_CONFIGURE_FLAG \
	> "$CONFIGURE_LOG" 2>&1 || CONFIGURE_STATUS=$?
cat "$CONFIGURE_LOG" >&2

if [ "$PROBE" = "1" ]; then
	# Stage 4 is the last stage of a probe. Publish the final configuration
	# and the audit whether the gates survived or not: a probe that hid the
	# evidence of a failure would be worthless.
	[ -f "$SOURCE_DIR/.config" ] ||
		fail "the probe produced no final configuration, so it cannot report what \`make defconfig\` did"
	cp "$SOURCE_DIR/.config" "$ARTIFACT_DIR/probe/final.config"
	if [ -f "$LOGS/final-config.json" ]; then
		cp "$LOGS/final-config.json" "$ARTIFACT_DIR/probe/config-audit.json"
	fi
	# The seed and the diff defconfig produced are the evidence that says
	# whether a lost package was never requested or was dropped.
	for evidence in seed.config pre-defconfig.config pre-defconfig-context.txt defconfig-diff.txt configure.log; do
		if [ -f "$LOGS/$evidence" ]; then
			cp "$LOGS/$evidence" "$ARTIFACT_DIR/probe/$evidence"
		fi
	done
	if [ "$CONFIGURE_STATUS" -eq 0 ]; then
		printf 'defconfig probe: every hard gate survived the final .config.\n'
		printf 'Probe evidence is in %s\n' "$ARTIFACT_DIR/probe"
		exit 0
	fi
	if [ "$CONFIGURE_STATUS" -eq 4 ]; then
		printf 'Error: the defconfig probe found hard gates missing from the final .config; the evidence is in %s\n' "$ARTIFACT_DIR/probe" >&2
		exit 4
	fi
	fail "the defconfig probe failed before it could audit the final configuration"
fi

if [ "$CONFIGURE_STATUS" -ne 0 ]; then
	fail "the configuration preflight of the firmware failed"
fi

# Stage 5 and 6: download and compile. Both keep their full log when they fail.
DOWNLOAD_LOG="$LOGS/download.log"
if ( cd "$SOURCE_DIR" && make download -j "$JOBS" ) > "$DOWNLOAD_LOG" 2>&1; then
	tail -5 "$DOWNLOAD_LOG"
else
	tail -40 "$DOWNLOAD_LOG" >&2
	fail "the package download failed, the log is kept in $DOWNLOAD_LOG"
fi

BUILD_LOG="$LOGS/build.log"
if ( cd "$SOURCE_DIR" && make -j "$JOBS" ) > "$BUILD_LOG" 2>&1; then
	tail -20 "$BUILD_LOG"
else
	tail -60 "$BUILD_LOG" >&2
	fail "the firmware build failed, the first stable error is in $BUILD_LOG"
fi

# Stage 7: image inspection. Both image roles are resolved by their role
# pattern and profile segment, never by an exact file name, because the
# buildroot resolves the name prefix only at build time. A missing, empty,
# ambiguous, oversized or wrongly typed image stops the build here.
python3 "$HELPER" artifacts --lock "$LOCK" --source-dir "$SOURCE_DIR" \
	--out "$LOGS/artifacts.json" > "$LOGS/artifacts.stdout" ||
	fail "the build did not produce the two inspected firmware image roles"
cat "$LOGS/artifacts.json"

# The package manifest of the build: every package the buildroot produced. It
# is evidence packaging, so it is collected only after both image roles exist:
# a run that only configured must fail on the missing image, not on the
# missing manifest.
PACKAGES="$LOGS/packages.txt"
( cd "$SOURCE_DIR" && find bin -name '*.ipk' -type f | LC_ALL=C sort ) > "$PACKAGES" || true
[ -s "$PACKAGES" ] ||
	fail "the build produced no package manifest, no image can be published"

# Stage 8: evidence packaging. It re-reads the images, the final
# configuration, the package manifest, the feed revisions and the logs.
BUILD_ENV_JSON=$(python3 - "$PLAN_FILE" "$JOBS" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    plan = json.load(handle)
target = plan.get("target") or {}
print(json.dumps(
    {
        "target": target.get("target"),
        "subtarget": target.get("subtarget"),
        "profile": target.get("profile"),
        "jobs": sys.argv[2],
    },
    sort_keys=True,
))
PY
)

python3 "$HELPER" publish --lock "$LOCK" --artifact-dir "$ARTIFACT_DIR" \
	--source-dir "$SOURCE_DIR" --feed-dir "$FEED_DIR" --packages "$PACKAGES" \
	--logs-dir "$LOGS" --build-env "$BUILD_ENV_JSON" ||
	fail "the firmware candidate could not be published"

printf 'Firmware candidates are in %s\n' "$ARTIFACT_DIR/images"
