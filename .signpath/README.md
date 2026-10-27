# Code signing with SignPath

The Windows executable can be signed for free by the
[SignPath Foundation](https://signpath.org/) open source program. The release
workflow (`.github/workflows/release.yml`) already contains the steps; they
run only when the repository is configured.

## 1. Apply

Apply at <https://signpath.org/apply> for the project
`https://github.com/mikysal78/openwisp-voucher`. Useful facts for the form:

- License: GPL-3.0-or-later (OSI approved), no proprietary parts.
- Built only on GitHub-hosted runners by `.github/workflows/release.yml`
  from a pushed tag; nothing is built or signed on a personal machine.
- Artifact to sign: one PyInstaller executable, `openwisp-voucher.exe`.
- Release builds already carry GitHub build provenance attestations.
- Maintainer: Michele Salerno (sole committer and approver).

## 2. Configure SignPath

In the SignPath project (slug `openwisp-voucher`):

- artifact configuration: the content of `artifact-configuration.xml`;
- trusted build system: GitHub.com, linked to this repository;
- signing policy `release-signing`, with manual approval.

## 3. Configure the repository

Settings → Secrets and variables → Actions:

| Kind | Name | Value |
|---|---|---|
| Secret | `SIGNPATH_API_TOKEN` | API token of a SignPath CI user (submitter) |
| Variable | `SIGNPATH_ORGANIZATION_ID` | SignPath organization ID |
| Variable | `SIGNPATH_PROJECT_SLUG` | only if different from `openwisp-voucher` |
| Variable | `SIGNPATH_POLICY_SLUG` | only if different from `release-signing` |

From the next tag the Windows job submits the executable, waits up to one
hour for the approval on signpath.io, checks the Authenticode signature and
publishes the signed file. The release notes then say it is signed.

## 4. Code signing policy

The SignPath Foundation asks the project to publish its code signing policy:
it is the "Code signing policy" section of `README.md` and `README.it.md`.
After the approval, update the "Code signing policy" section of the READMEs
(it currently says that the first application was not accepted).
For reference, the required content:

```markdown
## Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io/),
certificate by [SignPath Foundation](https://signpath.org/).

- Committers and reviewers: [Michele Salerno](https://github.com/mikysal78)
- Approvers: [Michele Salerno](https://github.com/mikysal78)

Only executables built by this repository's GitHub Actions from a release
tag are signed.

Privacy: this program connects only to the OpenWISP server configured by the
user and sends nothing elsewhere.
```
