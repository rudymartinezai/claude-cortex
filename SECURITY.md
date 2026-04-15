# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report security issues via [GitHub Security Advisories](https://github.com/rudymartinezai/claude-cortex/security/advisories).

You can expect:
- Acknowledgment within 48 hours
- A fix or mitigation plan within 7 days
- Credit in the release notes (unless you prefer anonymity)

## Security design

claude-cortex is a **local-only** tool. All data stays on your machine:

- **ChromaDB store**: `~/.cortex/store/` (directory permissions 0o700)
- **Knowledge graph**: `~/.cortex/knowledge_graph.db` (SQLite, local)
- **Session captures**: `~/.cortex/captures/` (JSONL, directory permissions 0o700)
- **Audit log**: `~/.cortex/wal/` (write-ahead log, directory permissions 0o700)

**No data is transmitted over the network.** The MCP server communicates via stdio only.

## Security measures

- Input validation on all region/cluster names (regex whitelist)
- SQL column name whitelisting in knowledge graph queries
- Trace ID format validation (hex only, max 64 chars)
- Secret scrubbing before indexing (API keys, tokens, passwords)
- Backup before destructive operations (DB migrations, config modifications)
- WAL audit trail for all write operations
- Dependency version pinning

## OWASP Top 10 audit

This project has been audited against the OWASP Top 10 (2021). See commit history for the full hardening pass.
