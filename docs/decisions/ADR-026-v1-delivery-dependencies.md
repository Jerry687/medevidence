# ADR-026: V1 local delivery dependencies

Decision date: 2026-09-14. Authority: current Owner delegates remaining V1
engineering decisions and completion. Supervisor selects these exact additions
for the already-required FastAPI/Streamlit/read-only MCP delivery interfaces.

- `streamlit==1.63.0`: approved V1 Python UI, calling FastAPI only.
- `uvicorn==0.52.4`: local ASGI server for the existing FastAPI application.
- `mcp==2.2.0`: current stable official MCP Python SDK, local stdio read-only
  adapter over stable application tools. No review/export mutations exposed.

Primary package metadata checked on the decision date:
[Streamlit](https://pypi.org/project/streamlit/),
[Uvicorn](https://pypi.org/project/uvicorn/), and
[MCP](https://pypi.org/project/mcp/). MCP v2 is the documented stable line; new
adapter code uses its current documented API rather than assuming v1 names.

These additions do not change the model provider, source semantics, report
approval, or access rights. Existing direct dependencies remain exactly pinned.
The lock records transitive versions and hashes. Dependency resolution and
package downloads are development network operations, not medical-source or
provider inference requests. Full offline validation and dependency audit are
required before final delivery; installing a package is not readiness evidence.

API/UI bind to loopback by default. MCP defaults to stdio, requires explicit
application composition, and must not create live transport during import,
construction or tools/list. No CLI extra is needed for the production adapter.
Secrets remain server-only. Streamlit analytics and external tracing are off
by default. React/public multi-user hosting remain postponed as in the PRD.

## Audit compatibility and declared licenses

The new exact lock has140 external identities:138 Windows-active and2 inactive
(the existing macOS torch identity and wasm-only httpx2-jsfetch1.0). Audit
reachability must evaluate the locked root/development/retrieval graph and
markers, not assume every unmarked package is installed on Windows. Preserve
the complete lock universe in SBOM/advisory/license evidence. The CPU-only
torch versions, registries and official wheel hashes are unchanged.

The inactive JSFetch wheel is acquired from its exact locked PyPI URL,6382
bytes, SHA256 `cb916b707601e69a07721aabc8f3f6659be3a6893bc1ff5c6f9e02241df2da32`.
Its verified METADATA declares BSD-3-Clause. Preserve the original wheel with
audit output so later reconciliation can independently verify this declaration.
Do not execute or install this inactive wheel to produce license evidence.

Approve the exact SPDX identifiers `MIT-0` (cffi2.1.1 metadata) and `MIT-CMU`
(Pillow12.3.0 metadata) in addition to existing allowed declarations. Primary
texts checked on the decision date:
[MIT No Attribution](https://spdx.org/licenses/MIT-0.html) and
[CMU License](https://spdx.org/licenses/MIT-CMU.html). Preserve package license
and copyright notices and the CMU license's notice and name-use conditions in
distribution materials. This approval does not make unknown declarations valid
or replace exact package-to-license evidence. The audit remains fail-closed for
missing, mismatched or ambiguous metadata and for unsupported license IDs.

Two exact installed legacy declarations additionally use file-backed resolution:
- protobuf7.36.1: legacy `3-Clause BSD License`, with METADATA SHA256
  `947ed3f132e70411555388d7fcd36712fdd60c8db6345001fb23bb56a2c6cab7`
  and LICENSE SHA256
  `6e5e117324afd944dcf67f36cf329843bc1a92229a8cd9bb573d7a83130fea7d`,
  resolves to BSD-3-Clause after inspecting its three-condition Google notice.
- pydeck0.9.3: legacy `Apache License 2.0`, with METADATA SHA256
  `c906606245b896f48f560a2175dc6ade991447f8e545dec8539678e1134eb71d`
  and licenses/LICENSE.txt SHA256
  `fa22bc5599b857a628e0757d4a95024f4c392aa2a4321053d61f34ce505d6d90`,
  resolves to Apache-2.0 from the explicit package notice.
These are exact package/version/path/hash bindings, not generic guesses from
ambiguous legacy strings. A changed file, metadata, version or declaration must
fail this fallback and require fresh evidence. Source/license notices are
preserved with the package and dependency inventory.

## Concrete read-only MCP projection

V1 MCP exposes `list_research_runs`, `get_research_run`, and
`get_research_report` through read-only application methods. Existing source
acquisition functions may persist snapshots and are not advertised as read-only
MCP calls. Report creation, source acquisition, approval, editing and export
remain API/UI workflow operations. This selects a real, implementable read-only
surface over the architecture's earlier illustrative source-tool names; it does
not expose unimplemented operations or grant new model/source capabilities.
