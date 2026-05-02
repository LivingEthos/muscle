# Security Policy

## Reporting A Vulnerability

Please open a private GitHub security advisory for this repository, or contact
the project maintainers through the repository owner if advisories are not
available.

Do not publish exploit details before maintainers have had a reasonable chance
to investigate and release a fix.

## Supported Versions

The current public branch is the supported development line until versioned
releases are tagged.

## Secret Handling

MUSCLE should never require committed API keys. Use environment variables such
as `MINIMAX_API_KEY` and provider base-url settings in your local shell or CI
secret store.

Before publishing changes, run a secret scan appropriate for your environment
and inspect staged files with:

```bash
git diff --cached --check
git diff --cached --name-only
```
