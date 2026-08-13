# Security Policy

## Supported Versions

We provide security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| >=0.4.2 | :white_check_mark: |
| <0.4.2  | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in edgeproc-core, please report it responsibly.

### How to Report

1. **Do NOT** open a public GitHub issue
2. Open a private [GitHub Security Advisory](https://github.com/hseshadr/edgeproc-core/security/advisories/new) (Security tab -> "Report a vulnerability")
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)

### What to Expect

- We will acknowledge receipt within 48 hours
- We will provide an initial assessment within 7 days
- We will keep you informed of the progress
- We will coordinate disclosure after a fix is available

### Disclosure Policy

- Vulnerabilities will be disclosed after a fix is available
- Credit will be given to reporters (if desired)
- A security advisory will be published on GitHub

## Security Best Practices

When using edgeproc-core:

1. **Partition Key Security**: Ensure partition keys are validated and not user-controlled
2. **Input Validation**: Validate all inputs before passing to library functions
3. **Access Control**: Implement proper access control at the application level
4. **Vector Index Security**: Secure your vector index implementations (database credentials, etc.)
5. **Metadata Sanitization**: Sanitize metadata before storing in embeddings

## Known Security Considerations

### Partition Key Isolation

The library provides partition key isolation, but **application-level access control is required**:

- Always validate partition keys from authenticated user context
- Never trust partition keys from user input
- Use Row Level Security (RLS) in databases when possible
- Implement proper authorization checks

### Vector Index Protocol

The `VectorIndex` protocol is abstract - security depends on your implementation:

- Secure database connections
- Use connection pooling with proper credentials
- Implement query timeouts
- Monitor for injection attacks in filter parameters

## Security Updates

Security updates will be:

- Released as patch versions (e.g., 0.1.1, 0.1.2)
- Documented in CHANGELOG.md
- Published as GitHub security advisories
- Backported to supported versions

The full trust, privacy, bounded-failure, and performance ownership contract is
documented in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## Thank You

Thank you for helping keep edgeproc-core and its users safe!
