# Multi-device OpenWrt build project design

## Intent

Create a personal firmware-build repository that starts with TR3000, x86_64, and Raspberry Pi, supports both upstream OpenWrt and ImmortalWrt, and remains easy to extend and safe for AI-assisted maintenance.

The repository will own build metadata, configuration layers, patches, custom files, and orchestration. Upstream source trees and generated firmware will be disposable working data rather than committed project structure.

## Goals

- Make the distinction between shared policy, distribution differences, and device differences obvious from directory names.
- Add a new device without copying an entire OpenWrt tree or duplicating common package selections.
- Allow the same device to target OpenWrt, ImmortalWrt, or both.
- Keep builds reproducible by recording source repository and revision in a machine-readable manifest.
- Use GitHub Actions as the primary compilation environment, with manual selection and matrix builds driven from the same manifests.
- Make scripts predictable, documented, and friendly to both humans and coding agents.
- Keep build output, downloaded source, caches, secrets, and private overrides out of version control.
- Provide a small validation path so malformed manifests and missing configuration layers fail before a long firmware build starts.

## Non-goals for the initial scaffold

- Shipping a verified firmware image for every listed device.
- Hiding OpenWrt's native `.config`, feeds, patches, or files overlay behind a large custom framework.
- Maintaining upstream source as Git submodules.
- Encoding credentials, private keys, Wi-Fi passwords, or other personal secrets in tracked files.
- Building a web interface or general-purpose firmware build service.

## Anti-goals

- One complete copied configuration tree per distribution and device.
- Editing files directly inside a downloaded upstream checkout and treating those edits as the project source of truth.
- Scripts with implicit current-directory assumptions or unexplained environment variables.
- AI instructions that allow broad rewrites of known-good device configuration without validation.

## Chosen approach

Use a layered, device-centred repository:

1. Common policy is shared across all builds.
2. Distribution layers contain only OpenWrt/ImmortalWrt differences.
3. Device layers contain target/profile selection and hardware-specific additions.
4. Optional local, untracked overrides contain secrets and machine-specific choices.

Build preparation materializes these layers into a disposable source checkout. The native OpenWrt build system remains visible and is invoked normally.

### Alternatives considered

- **Fully separate OpenWrt and ImmortalWrt trees:** simplest to understand initially, but duplicates device definitions, package selections, and scripts. Rejected because divergence grows with every device.
- **Manifest-generated configuration framework:** highly automated, but introduces a second configuration language and makes native OpenWrt troubleshooting harder. Rejected for the initial version; manifests will describe builds, not replace native config fragments.
- **Layered device-centred layout:** selected because it minimizes duplication while keeping every applied fragment and overlay inspectable.

## Proposed repository layout

```text
.
├── AGENTS.md
├── README.md
├── .editorconfig
├── .gitignore
├── docs/
│   ├── architecture.md
│   ├── adding-a-device.md
│   ├── configuration-layers.md
│   └── superpowers/specs/
├── manifests/
│   ├── sources.yml
│   └── devices/
│       ├── tr3000.yml
│       ├── x86-64.yml
│       └── raspberry-pi.yml
├── configs/
│   ├── common/
│   │   ├── base.config
│   │   └── packages.config
│   ├── distributions/
│   │   ├── openwrt.config
│   │   └── immortalwrt.config
│   └── devices/
│       ├── tr3000.config
│       ├── x86-64.config
│       └── raspberry-pi.config
├── feeds/
│   ├── common.conf
│   ├── openwrt.conf
│   └── immortalwrt.conf
├── overlays/
│   ├── common/files/
│   └── devices/
│       ├── tr3000/files/
│       ├── x86-64/files/
│       └── raspberry-pi/files/
├── patches/
│   ├── common/
│   ├── distributions/
│   │   ├── openwrt/
│   │   └── immortalwrt/
│   └── devices/
│       ├── tr3000/
│       ├── x86-64/
│       └── raspberry-pi/
├── scripts/
│   ├── bootstrap.sh
│   ├── build.sh
│   ├── clean.sh
│   ├── list-targets.sh
│   ├── prepare.sh
│   ├── validate.sh
│   └── lib/
├── local/
│   └── README.md
├── tests/
│   └── structure/
├── .github/
│   ├── workflows/
│   │   ├── build.yml
│   │   ├── validate.yml
│   │   └── reusable-build.yml
│   └── actions/
├── work/                 # ignored: upstream checkouts and temporary state
├── output/               # ignored: firmware and build reports
└── cache/                # ignored: download/compiler caches
```

Empty extension directories will contain short `.gitkeep` or README files only where needed to preserve their purpose in Git.

## Manifest model

`manifests/sources.yml` records distribution source URLs, supported branches/revisions, and default revision policy. Each file under `manifests/devices/` uses a stable device identifier and records:

- display name and optional hardware revision notes;
- supported distributions;
- native OpenWrt target, subtarget, and profile identifiers;
- ordered configuration fragments;
- ordered feeds, patches, and files overlays;
- expected firmware artifact patterns;
- device-specific documentation links or cautions.

TR3000 model/revision-specific OpenWrt profile details and Raspberry Pi board variants must be verified before claiming a build is ready. The initial structure may represent unresolved values explicitly rather than guessing them.

## Configuration and preparation flow

For a selected distribution and device, preparation will apply data in this order:

```text
common → distribution → device → local untracked override
```

The same precedence applies to configuration fragments, feeds, patches, and root filesystem overlays. Later layers may add or intentionally override earlier layers. Preparation produces a report listing the source revision and every applied input.

Configuration remains in native OpenWrt `CONFIG_...` fragment format. The preparation script composes fragments, invokes `make defconfig`, and preserves the resulting resolved `.config` in the build report. It must not silently commit the generated file.

## GitHub Actions and script interface

GitHub Actions on Linux is the primary compilation environment. Repository build scripts therefore use portable Bash and expose the same operations used by CI; workflow YAML should orchestrate rather than duplicate build logic. Windows users may edit manifests and run lightweight checks through WSL2 or Git Bash, but native Windows compilation is not supported.

`build.yml` provides a manual `workflow_dispatch` entry point with distribution, device, source revision, and optional package/build flags. It may also build a selected manifest-defined matrix on a schedule or release event once those policies are enabled. `reusable-build.yml` owns one distribution/device job so future release or batch workflows can reuse it. `validate.yml` runs on pull requests and relevant pushes without compiling firmware. GitHub-hosted Ubuntu runners are the initial default; self-hosted runners remain a later manifest/workflow option rather than an initial requirement.

Each build job will:

1. validate the selected manifest combination;
2. restore safe download/compiler caches keyed by distribution, revision, target, and configuration inputs;
3. fetch the pinned upstream source and feeds;
4. apply ordered configuration, patch, and files-overlay layers;
5. run `make defconfig`, dependency download checks, and the native build;
6. collect the resolved configuration, source revision, package list, checksums, logs, and matching firmware images;
7. upload a predictably named GitHub Actions artifact even when diagnostic logs are the only useful result.

Credentials, signing keys, and private configuration must come from GitHub Actions secrets or an explicitly untracked local layer. Untrusted pull-request workflows must never receive secrets. Workflow permissions will be minimal and actions will be pinned to stable major versions or immutable revisions according to maintainability needs.

The intended commands are:

- `scripts/list-targets.sh` — list distribution/device combinations from manifests.
- `scripts/validate.sh` — validate layout, manifest references, required fragments, and duplicate identifiers without compiling.
- `scripts/bootstrap.sh` — fetch or update an isolated upstream checkout and required feeds.
- `scripts/prepare.sh` — apply ordered layers and create the resolved build configuration/report.
- `scripts/build.sh` — run validation, preparation, and the native build with a chosen job count.
- `scripts/clean.sh` — remove only explicitly selected disposable work/output state; no broad implicit deletion.

The initial scaffold implements validation and discovery fully while leaving source fetch/build operations as safe, documented skeletons until exact source revisions and hardware profiles are supplied. It must fail clearly on unresolved manifest values instead of pretending to produce a valid image. Delivering verified firmware is a later milestone, not part of the initial structure task.

Common and distribution configuration fragments initially contain only documented, conservative examples required to demonstrate layering. Personal package policy, image sizing, LuCI selection, network defaults, and other opinionated firmware behavior remain explicit TODOs until requested; they will not be guessed.

## AI collaboration contract

`AGENTS.md` will be the short operational entry point for coding agents. It will state:

- read the target manifest and configuration-layer documentation before editing;
- never edit generated files under `work/`, `output/`, or `cache/`;
- keep device-specific behavior inside its device layer unless it is truly shared;
- never commit secrets or local overrides;
- validate references and run structure tests after changes;
- preserve native OpenWrt configuration syntax and explain any intentional override;
- avoid changing multiple device profiles while addressing one device unless the common layer is deliberately being changed.

README documentation will include copyable commands and a map from common tasks to directories so a new human or agent can find the correct edit point quickly.

## Safety and privacy

- `local/**` is ignored except for its explanatory README and example templates.
- Generated source, build output, caches, logs, private keys, and environment files are ignored.
- Scripts never require secrets in command-line arguments when a file or environment-based mechanism is appropriate.
- Cleanup resolves and verifies its target beneath `work/`, `output/`, or `cache/` before deletion.

## Validation and acceptance

The scaffold is accepted when:

- the documented tree exists and repository navigation links resolve;
- all three initial device manifests parse and identify supported distributions without inventing unknown hardware profile values;
- source and layer references are validated by one command;
- adding a fourth example device can be explained without modifying core scripts;
- ignored generated/private directories do not appear as tracked build data;
- scripts provide useful help and reject invalid distribution/device pairs before attempting a build;
- validation runs independently from expensive compilation on pull requests;
- a manually dispatched GitHub Actions build can select a manifest entry, rejects unresolved target/revision values clearly, and is structurally ready to upload firmware plus a reproducibility report once those values are completed;
- documentation clearly identifies GitHub Actions as the main builder and Linux/WSL2 as the optional local path.

## Builder decisions left open

- Choose a lightweight YAML parser strategy that does not make basic validation fragile on a clean Windows machine; a JSON-compatible subset or PowerShell data files may be substituted if this materially improves zero-dependency use, while retaining machine-readable manifests.
- Choose the exact structure-test framework based on what is already available locally.
- Choose conservative artifact retention, concurrency cancellation, cache size, and scheduled-build defaults; document them so they can be changed without editing build scripts.
- Initialize Git as part of implementation because GitHub Actions is the primary builder and the project is intended for GitHub; no remote will be invented or configured.
