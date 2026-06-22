"""Checkpoint hosted service: a protocol-first HTTP API for hosting Checkpoint repos.

Built on the standard library only (http.server + urllib) so the service inherits the
core's local-first, no-Git, zero-dependency guarantees. The server never weakens the
protocol: it verifies object hashes, schemas, seals, parent chains, signatures, and policy
before any ref moves, and it never trusts the client.
"""

API_VERSION = "0.8"
PROTOCOL_VERSION = "0.8"
