# axe-core (test asset)

The accessibility rules engine used by `tests/test_accessibility.py` (#83). It is injected
into pages in headless Chrome over the DevTools protocol; it is never served by the app or
shipped in the wheel.

- Version: 4.14.0 (released 2026-10-05)
- Source: https://cdn.jsdelivr.net/npm/axe-core@4.14.0/axe.min.js (the npm package
  `axe-core`, file `axe.min.js`, unmodified)
- SHA-256: `20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878`
  (checked by `test_vendored_axe_is_the_pinned_release`)
- Licence: Mozilla Public License 2.0, copyright Deque Systems, Inc. (`LICENSE`, from the
  same release)

To update: download the new release's `axe.min.js` and `LICENSE` from the same URL with
the new version, then update the version and hash here and in `AXE_VERSION` and
`AXE_SHA256` in `tests/test_accessibility.py`.
