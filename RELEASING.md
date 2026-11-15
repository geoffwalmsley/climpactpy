# Releasing climpact and climpact-web

Publishing a **GitHub Release** is the only thing that publishes anything (#131, #122,
epic #12). It uploads the two Python packages, `climpact` and `climpact-web`, to TestPyPI
and then PyPI, attaches the built files to the release, and pushes the
`ghcr.io/geoffwalmsley/climpact-web` image. Merging to `main` publishes nothing.

- The two packages share **one version number** and are always released together.
  climpact-web requires `climpact[plots]` at exactly its own version, so a web install never
  gets a mismatched core.
- Versions follow [SemVer](https://semver.org/), starting at `0.1.0`, written in their
  [PEP 440](https://peps.python.org/pep-0440/) form. Tags are `v` plus the version: `v0.1.0`,
  `v0.2.0rc1`.
- **Pre-releases** (`a`, `b` or `rc` versions, released with GitHub's *Set as a
  pre-release* box) go to TestPyPI only, never PyPI. They push the image as `X.Y.ZrcN`, never
  `latest`, so they don't deploy.
- Releases go to TestPyPI, then, after the maintainer approves the `pypi` deployment, to
  PyPI. The image is pushed as `X.Y.Z` and `latest`.
- No API token exists anywhere: both indexes accept uploads from `release.yml` through
  **Trusted Publishing** (OpenID Connect), and the image is pushed with the workflow's own
  `GITHUB_TOKEN`.

What the workflow checks and in what order is in the header of
[`.github/workflows/release.yml`](.github/workflows/release.yml) and in TECHNICAL.md ›
"Releases and PyPI".

## One-time setup (before the first release)

Do these once, in the web UIs. Nothing here goes in the repository.

### 1. TestPyPI: pending publishers

1. Make an account on <https://test.pypi.org/account/register/> (it is separate from
   PyPI), verify its email address and turn on two-factor authentication.
2. Open <https://test.pypi.org/manage/account/publishing/>. Under *Add a new pending
   publisher*, choose **GitHub** and fill in:

   | Field | Value |
   | --- | --- |
   | PyPI Project Name | `climpact` |
   | Owner | `geoffwalmsley` |
   | Repository name | `climpactpy` |
   | Workflow name | `release.yml` |
   | Environment name | `testpypi` |

   and press *Add*.
3. Add **only `climpact`** for now. PyPI and TestPyPI refuse a second pending publisher with
   the same repository, workflow and environment ("already been registered for a different
   project name"). `climpact-web`'s publisher is added during the first release: see
   *The first upload to each index* below.

### 2. PyPI: pending publishers

1. Sign in at <https://pypi.org/> (two-factor authentication is required).
2. Open <https://pypi.org/manage/account/publishing/> and add one **GitHub** pending
   publisher as above, with **Environment name `pypi`**:

   | Field | Value |
   | --- | --- |
   | PyPI Project Name | `climpact` (`climpact-web` comes later, as above) |
   | Owner | `geoffwalmsley` |
   | Repository name | `climpactpy` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

### The first upload to each index

The release uploads the files in name order, so `climpact` goes first. On the first release
to an index (`v0.1.0rc1` for TestPyPI, `v0.1.0` for PyPI):

1. The upload job creates `climpact`, then fails on `climpact-web` with "Non-user identities
   cannot create new projects". This is expected, once.
2. `climpact`'s publisher is now an ordinary one, so the index accepts a pending publisher for
   **`climpact-web`** with the same repository, workflow and environment. Add it.
3. In the run, *Re-run failed jobs* (and approve `pypi` again on PyPI). The upload skips the
   files the index already has and the rest of the run continues.

Later releases upload both packages in one go.

A pending publisher does not reserve the name: whoever uploads first creates the project.
Both names were free on 2026-11-14; check again just before the first release. The first
successful upload turns each pending publisher into an ordinary one, and the project then
belongs to your account.

### 3. GitHub: the two environments

In the repository, *Settings → Environments → New environment*:

1. **`testpypi`**: no reviewers. Under *Deployment branches and tags* choose *Selected
   branches and tags*, *Add deployment branch or tag rule*, **Ref type: Tag**, pattern
   `v*`. Save.
2. **`pypi`**: tick **Required reviewers** and add `geoffwalmsley`. Leave *Prevent
   self-review* **unticked** (you are the only maintainer, so you approve your own
   releases). Add the same tag rule, `v*`. Save.

The tag rule means only a run for a `v*` tag (a release) can use the environment, so no
branch or pull request can reach the publish jobs. Add no secrets to either environment.

Optionally, a tag ruleset (*Settings → Rules → Rulesets → New tag ruleset*, target
`v*`, restrict creations, updates and deletions, bypass for yourself) stops anyone else
from creating release tags.

## Cutting a release

The same steps for every version; the first two are below.

1. **Bump PR.** From an up-to-date `main`:

   ```sh
   git switch -c release-0.1.0rc1 main
   uv run python scripts/set_version.py 0.1.0rc1   # both __version__ values and the pin
   uv lock
   ```

   In `CHANGELOG.md`, rename `## Unreleased` to `## 0.1.0rc1 - YYYY-MM-DD` (today) and
   start a new empty `## Unreleased` above it. Commit (signed), push, open a pull request,
   wait for CI (its `dist` job builds and smoke-tests the packages at the new version) and
   merge it with a merge commit.

2. **Publish the GitHub Release** from `main`:
   *Releases → Draft a new release → Choose a tag*: type `v0.1.0rc1` and pick *Create new
   tag: v0.1.0rc1 on publish*, target **`main`**; title `v0.1.0rc1`; notes: the changelog
   entry; tick **Set as a pre-release** for an `a`/`b`/`rc` version (and only then);
   *Publish release*. Or from the command line:

   ```sh
   gh release create v0.1.0rc1 --target main --prerelease --title v0.1.0rc1 \
     --notes "See CHANGELOG.md"
   ```

   (drop `--prerelease` for a final version).

3. **Watch** *Actions → Release*. The jobs, in order:
   - `version` fails at once if the tag isn't `v` + both `__version__` values + the pin,
     if the pre-release box doesn't match the version, or if the tagged commit isn't on
     `main`. Nothing has been uploaded then: see *When something fails*.
   - `test` (the full suite with R parity) and `build` (sdists and wheels, checked and
     smoke-tested in a clean virtualenv) run side by side.
   - `testpypi` uploads, and `testpypi-check` checks TestPyPI serves exactly the built files
     and smoke-tests the wheels downloaded from it.
   - `pypi` (final releases only) waits for you: open the run, *Review deployments*, tick
     `pypi`, *Approve and deploy*.
   - `assets` attaches the four files to the GitHub Release; `image` builds, smoke-tests
     and scans the image; `publish` pushes it to ghcr.io.

4. **Check** the result:

   ```sh
   python3.12 -m venv /tmp/climpact-rc   # any Python 3.12 or newer && . /tmp/climpact-rc/bin/activate
   pip install --index-url https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ climpact-web==0.1.0rc1
   climpact --version          # Climpact for Python 0.1.0rc1 (port of Climpact 3.4.3)
   climpact-web                # opens the app
   docker pull ghcr.io/geoffwalmsley/climpact-web:0.1.0rc1
   ```

   For a final release use `pip install climpact-web==0.1.0` (PyPI) and `:0.1.0`/`:latest`.
   After the very first image, open the package on GitHub (*your profile → Packages →
   climpact-web → Package settings*) and make it **public** if it isn't, so the Droplet
   can pull it without credentials (TECHNICAL.md › "Image in CI and on ghcr.io").

### The first two releases

- **`v0.1.0rc1`** (pre-release): bump PR with `scripts/set_version.py 0.1.0rc1`, then a
  release with *Set as a pre-release* ticked. It creates both projects on **TestPyPI**,
  attaches the files to the release, and pushes the **first image**,
  `ghcr.io/geoffwalmsley/climpact-web:0.1.0rc1` (no `latest`), which #123 (the Droplet)
  is waiting for. PyPI is untouched.
- **`v0.1.0`**: bump PR with `scripts/set_version.py 0.1.0`, then a release with the box
  unticked. TestPyPI gets `0.1.0`, then after your approval it creates both projects on
  **PyPI**, and the image is pushed as `0.1.0` and `latest`.

## When something fails

- **Before any upload** (`version`, `test` or `build` failed): delete the release and its tag
  (`gh release delete vX.Y.Z --cleanup-tag`), fix it on `main` through a pull request, and
  publish the release again with the same version.
- **After an upload**: an index never accepts a file name twice, even after deletion, so a
  version that reached TestPyPI or PyPI is spent there. If the failure was transient (a
  network error, TestPyPI slow to list the files), *Re-run failed jobs*: the uploads skip
  files an index already has (`uv publish --check-url`). If the release itself is wrong,
  release the next version (`rc2`, or a patch `0.1.1`) instead.
- **A bad release on PyPI**: *yank* it in the project's PyPI settings (pip then skips it
  unless asked for exactly) and release a fix. Never delete a release from PyPI.
- **Rejected approval** of `pypi`: TestPyPI already has the version; nothing reached PyPI
  or ghcr.io. Release the next version when ready.

## Handover

PyPI ownership of `climpact` and `climpact-web` moves to a WMO account at handover (#12):
add the WMO account as an owner of both projects on PyPI and TestPyPI, then decide whether
to stay on as a maintainer. The publishers (this repository and `release.yml`) stay valid
as long as the repository does; if the repository moves, update them on both indexes.
