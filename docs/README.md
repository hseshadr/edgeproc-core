# edgeproc-core Documentation

## Documents

### [installation-guide.md](./installation-guide.md)
How to install this package in your projects:
- Installing a pinned release from PyPI, or a pinned commit from source
- Adding to pyproject.toml and requirements.txt
- Verifying the install actually imports
- Troubleshooting common issues

### [vector-mgmt-architecture.md](./vector-mgmt-architecture.md)
Complete specification for HNSW indexing and partitioning strategies:
- The three partitioning strategies the library ships: global, bucketed, two-tier
- Support for any partition key (tenant_id, user_id, org_id, etc.)
- When to rebuild HNSW indices
- Atomic swap reindexing patterns
- Query optimization and scaling guidelines

## Library Usage

See the main [README.md](../README.md) for installation and usage examples.

## Design Principles

- **Protocol-based**: Use Python Protocols for abstractions
- **Type-safe**: Full Pydantic models and type hints
- **Generic & Reusable**: Supports any partition key, not just tenant_id
- **Backward Compatible**: Existing tenant_id-based code continues to work
- **Testable**: Clean interfaces enable easy testing

## Partition Key Flexibility

The library supports generic partition keys, allowing you to partition by:
- **Tenant ID**: Multi-tenant SaaS applications
- **User ID**: Per-user data isolation
- **Organization ID**: Enterprise organization boundaries
- **Category ID**: Content categorization
- **Custom Composite Keys**: Any combination via custom extractors

All partitioning strategies work with any partition key through the `partition_key_name` parameter.

