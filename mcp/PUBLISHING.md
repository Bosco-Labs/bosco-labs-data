# Publishing the MCP server (owner steps)

Releases go out from this public repo through the GitHub Actions workflow
[`.github/workflows/publish-mcp.yml`](../.github/workflows/publish-mcp.yml):

1. job `pypi`: checks that the versions match, runs the tests, builds `mcp/` and uploads it to
   PyPI as `bosco-labs-data-mcp` with trusted publishing (no API token);
2. job `mcp-registry`: installs a pinned, signature-verified `mcp-publisher`, validates
   `server.json`, logs in with GitHub OIDC and publishes `io.github.Bosco-Labs/bosco-labs-data`
   to the official MCP Registry. The registry checks PyPI ownership through the
   `mcp-name:` comment on the first line of `mcp/README.md`.

No secrets are needed. The steps below are done once, except "Release a new version".

## 1. PyPI account

Create an account at https://pypi.org/account/register/, verify the email address and turn on
two-factor authentication (PyPI requires it).

## 2. Pending trusted publisher on PyPI

At https://pypi.org/manage/account/publishing/, under "Add a new pending publisher", choose
**GitHub** and enter:

| Field | Value |
|---|---|
| PyPI Project Name | `bosco-labs-data-mcp` |
| Owner | `Bosco-Labs` |
| Repository name | `bosco-labs-data` |
| Workflow name | `publish-mcp.yml` |
| Environment name | `pypi` |

A pending publisher does not reserve the name: the project is created on the first successful
upload. After that the publisher shows under the project's "Publishing" settings.

## 3. GitHub environment `pypi`

The first workflow run creates the `pypi` environment automatically, but without any protection.
Better: create it first in the repo under Settings -> Environments -> New environment, name
`pypi`, and

- under "Deployment branches and tags", allow only tags matching `mcp-v*` (and `main` if you
  want to start runs by hand from the Actions tab);
- optionally add yourself as a required reviewer, so every release waits for your approval.

## 4. Run the workflow

Either push a tag (from an up-to-date `main`):

```bash
git tag mcp-v0.1.0
git push origin mcp-v0.1.0
```

or open Actions -> "Publish MCP server" -> "Run workflow" on `main`. The tag must equal the
version in `mcp/pyproject.toml` (the workflow fails otherwise).

Check the result:

- PyPI: https://pypi.org/project/bosco-labs-data-mcp/ and `uvx bosco-labs-data-mcp` starts
  the server (it waits on stdin; stop it with Ctrl+C).
- MCP Registry:
  `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Bosco-Labs/bosco-labs-data"`

If the PyPI job succeeded and the registry job failed, use "Re-run failed jobs" (re-running the
whole workflow also works: the PyPI upload skips files that already exist).

## Release a new version

Bump the version in three places, in one commit: `mcp/pyproject.toml` (`version`) and
`mcp/server.json` (`version` and `packages[0].version`). Then tag `mcp-v<version>` as above.
The registry refuses a version it already has, and PyPI never accepts the same file twice.

## 5. Glama

`glama.json` in the repo root names `Bosco-Labs` as maintainer, which lets that GitHub account
claim the listing.

1. Sign in at https://glama.ai with GitHub (`Bosco-Labs`).
2. At https://glama.ai/mcp/servers click "Add Server" and submit
   `https://github.com/Bosco-Labs/bosco-labs-data`.
3. Once it is indexed, claim the server on its Glama page. The server lives in `mcp/`, not
   the repo root: if Glama's checks or its build fail, set the build/start settings in the
   server's admin page (install and start with `uvx bosco-labs-data-mcp`, environment variable
   `APIFY_TOKEN`).

## 6. Smithery

Smithery is now part of Arcade. Its notice at https://smithery.ai/future says the Smithery API,
CLI, accounts and connection services shut down on 31 October 2026 and that smithery.ai stays as
a curated public directory; it gives no self-service way to add a local (stdio) server. So
there is nothing to submit for now. `mcp/smithery.yaml` is kept in case listing reopens: it
describes a local stdio server started with `uvx bosco-labs-data-mcp` and a required
`apifyToken` setting. Smithery reads that file from the repo root by default; set the base
directory to `mcp` when adding the server. To ask about a listing, use the contact on
https://smithery.ai/future.

The official MCP Registry (step 4) is the main listing: other directories, such as PulseMCP,
import from it.
