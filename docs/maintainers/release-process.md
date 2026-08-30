# Release process

1. Ensure `main` is green (Quality Gate + Security Gate).
2. Update `CHANGELOG.md`: move Unreleased to the new version with the date.
3. Bump `version` in `pyproject.toml` and `__version__` in
   `src/allwr_toolkit/__init__.py`.
4. Write `docs/release-notes/vX.Y.Z.md`: features **and known limitations**.
5. Merge via PR; tag `vX.Y.Z` on the merge commit (protected tag — only
   maintainers can create it).
6. The release workflow re-runs all checks, builds wheel+sdist, validates
   metadata, generates SHA256 checksums and a CycloneDX SBOM, attests
   provenance and publishes the GitHub release with all artifacts.
7. Verify from a clean environment:
   `pip install <wheel-url>` → `allwr-toolkit version` → quickstart dry run.
8. No PyPI publishing until naming and policy are approved (then: OIDC
   trusted publishing only).

No production credentials are used anywhere in release validation.
