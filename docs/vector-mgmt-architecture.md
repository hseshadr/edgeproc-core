# Vector Management Architecture

## Overview

This document specifies the HNSW vector indexing and partitioning strategy for multi-tenant vector search systems, focusing on efficient tenant isolation without the overhead of per-tenant indices.

This is a general-purpose strategy that can be applied to any vector search system requiring multi-tenant isolation.

**Core Principle**: Do NOT create "one HNSW per tenant/user." Instead, use global or bucketed indices with metadata filtering and routing.

## Architecture Diagrams

| Diagram | Description |
|---------|-------------|
| ![Partitioning Strategies](diagrams/partitioning-strategies.png) | Comparison of Global, Bucketed, and Two-Tier strategies |
| ![Query Flow](diagrams/query-flow.png) | End-to-end query lifecycle |
| ![Reindex Pattern](diagrams/reindex-atomic-swap.png) | Background reindex with atomic swap |
| ![Scale Decision Tree](diagrams/scale-decision-tree.png) | Choosing the right strategy based on scale |

---

## Partitioning Patterns (Ordered by Scale)

### 1. Single Global HNSW + Metadata Filter (Default for < 50K Users)

**Strategy:**
- One global HNSW index containing all entity embeddings
- Each embedding row stores:
  - `tenant_id` (for tenant isolation)
  - `entity_id`
  - `source_list` (OFAC, EU, custom list, etc.)
  - `risk_category` (SANCTION, PEP, CUSTOM)
  - `entity_type` (PERSON, ORGANIZATION)
  - `created_at`

**Query Flow:**
1. Embed query name
2. Execute ANN search with HNSW
3. Apply post-filter: `WHERE tenant_id = X AND source_list IN (enabled_lists)`
4. Return top K matches

**Pros:**
- Simplest operational model
- Best index reuse
- No per-tenant overhead
- Single index to maintain

**Cons:**
- Requires efficient filtered ANN (pgvector supports this)
- Post-filtering can reduce recall if tenant subset is very small
- All tenants share index build/maintenance overhead

**Best For:**
- < 50K tenants
- Most common queries involve shared global sanctions lists
- Tenants with similar list configurations

**Implementation Example (pgvector):**
```sql
-- Query pattern
SELECT entity_id, embedding <=> $1 AS distance
FROM embeddings
WHERE tenant_id = $2 OR tenant_id IS NULL  -- Global + tenant data
  AND category = ANY($3)  -- Additional filters
ORDER BY distance
LIMIT $4;
```

---

### 2. Bucketed HNSW by Tenant Hash (50K - 5M Users)

**Strategy:**
- Partition entities into N buckets (e.g., 256 or 1024)
- Bucket assignment: `bucket_id = hash(tenant_id) % N`
- Each bucket has its own HNSW index
- Within each bucket, still filter by `tenant_id` for isolation

**Schema Example (pgvector):**
```sql
-- Embeddings table with bucket
CREATE TABLE embeddings (
    entity_id VARCHAR(500) PRIMARY KEY,
    tenant_id VARCHAR(100),
    bucket_id SMALLINT GENERATED ALWAYS AS (hash(tenant_id) % 256) STORED,
    embedding vector(1536),
    ...
);

-- HNSW index per bucket (or composite index with bucket_id)
CREATE INDEX idx_embeddings_bucket_hnsw ON embeddings
USING hnsw (embedding vector_cosine_ops)
WITH (m = 32, ef_construction = 200);

-- Partition index by bucket
CREATE INDEX idx_embeddings_bucket_tenant ON embeddings(bucket_id, tenant_id);
```

**Query Flow:**
1. Compute `bucket_id = hash(tenant_id) % N`
2. Route query to that bucket's HNSW
3. Execute ANN search within bucket
4. Apply tenant_id filter (cheap within bucket)
5. Return top K matches

**Pros:**
- Keeps HNSW indices smaller → faster searches
- Predictable memory growth per bucket
- Avoids "filter after ANN across millions"
- Better isolation between tenants

**Cons:**
- More operational complexity (N indices)
- Need rebalancing strategy if tenant distribution is skewed
- Cross-bucket queries are more complex (if needed)

**Best For:**
- 50K - 5M tenants
- Want consistent latency guarantees
- Need better tenant isolation
- Tenant data distribution is relatively uniform

**Scaling Rules:**
- Start with 256 buckets
- Increase to 1024 when individual buckets exceed ~1M vectors
- Monitor bucket sizes; rebalance if skew > 2x

---

### 3. Two-Tier: Hot Cache + Global Cold Index

**Strategy:**
- **Hot tier**: Recent entities per tenant (last N entities, last M days)
  - Small per-tenant in-memory cache or tiny HNSW
  - OR brute-force search (K is small)
- **Cold tier**: Global/bucketed HNSW for all historical entities

**Schema Example:**
```sql
-- Hot cache table (recent embeddings only)
CREATE TABLE embeddings_hot (
    entity_id VARCHAR(500) PRIMARY KEY,
    tenant_id VARCHAR(100),
    embedding vector(1536),
    created_at TIMESTAMPTZ,
    ...
) PARTITION BY RANGE (created_at);

-- Cold global index (all embeddings)
CREATE TABLE embeddings_cold (
    entity_id VARCHAR(500) PRIMARY KEY,
    tenant_id VARCHAR(100),
    embedding vector(1536),
    ...
);
```

**Query Flow:**
1. Search hot cache (filtered by tenant_id)
2. Search cold index (filtered by tenant_id)
3. Merge results
4. Rerank (optional)
5. Return top K

**Pros:**
- Extremely fast for recent entities
- Reduces load on large cold index
- Better cache locality

**Cons:**
- More moving pieces
- Dual-write complexity
- Cache invalidation strategy needed

**Best For:**
- Chat/assistant use cases where most queries hit recent data
- Very large historical datasets
- Time-sensitive recent data queries

**Retention Policy:**
- Entities older than 30 days move from hot → cold
- Background job moves data daily

---

### 4. Hierarchical Summaries (Long-Term Memory)

**Strategy:**
- Don't embed every raw entity for long-term recall
- Maintain hierarchical levels:
  - **L0**: Raw entity embeddings (short TTL, 30-90 days)
  - **L1**: List-level summaries (per source_list, per version)
  - **L2**: Tenant-level summaries (daily/weekly aggregated)
  - **L3**: Global summaries (stable, long-term patterns)

**Schema Example:**
```sql
-- L0: Raw embeddings (current active set)
CREATE TABLE embeddings_l0 (...);

-- L1: Collection summaries
CREATE TABLE embeddings_l1 (
    collection_id VARCHAR(100),
    collection_version VARCHAR(50),
    summary_embedding vector(1536),
    item_count INTEGER,
    ...
);

-- L2: Tenant summaries
CREATE TABLE embeddings_l2 (
    tenant_id VARCHAR(100),
    date DATE,
    summary_embedding vector(1536),
    ...
);
```

**Query Routing:**
- "Recent items": Search L0
- "Collection-level patterns": Search L1
- "Tenant history": Search L2
- "Global patterns": Search L3

**Pros:**
- Huge speed + memory win
- Better signal/noise than embedding raw items
- Scales to very long histories

**Cons:**
- Needs summarization pipeline
- More complex query routing
- Potential information loss in summarization

**Best For:**
- Long-running tenant histories
- Very large item sets per tenant
- Pattern-based queries vs exact matches

---

## Recommended Design Pattern

### Phase 1: Single Global HNSW + Metadata Filter

**Rationale:**
- Start simple
- Most vector DBs support efficient filtered ANN
- Most queries involve shared data across tenants
- < 50K tenants initially

**Implementation Example (pgvector):**
```sql
-- Single global HNSW index
CREATE INDEX idx_embeddings_hnsw ON embeddings
USING hnsw (embedding vector_cosine_ops)
WITH (m = 32, ef_construction = 200);

-- Supporting indexes for filtering
CREATE INDEX idx_embeddings_tenant ON embeddings(tenant_id) 
WHERE tenant_id IS NOT NULL;
```

**Query Pattern:**
```sql
-- Example query with tenant filtering
SELECT entity_id, embedding <=> $1 AS distance
FROM embeddings
WHERE (tenant_id = $2 OR tenant_id IS NULL)  -- Global + tenant data
  AND metadata->>'category' = ANY($3)  -- Additional filters
ORDER BY distance
LIMIT $4;
```

### Phase 2: Bucketed HNSW (When Scale Requires)

**Migration Path:**
1. Add `bucket_id` computed column
2. Create partitioned tables or bucket-filtered indexes
3. Build new HNSW indices per bucket (background)
4. Atomic swap to new indices
5. Update query routing logic

**Trigger Conditions:**
- > 50K tenants
- Individual index exceeds 10M vectors
- Query latency > 200ms (p95) consistently
- Index build time > 30 minutes

---

## When to Rebuild HNSW Indices

### Mandatory Rebuild Triggers

#### 1. Embedding Model Changes
Rebuild if ANY of these change:
- Embedding model (e.g., `text-embedding-3-small` → `text-embedding-3-large`)
- Model dimensions (e.g., 1536 → 3072)
- Normalization strategy (cosine vs dot product)
- Distance metric (cosine ↔ L2)
- Chunking/embedding strategy that changes vector distribution

**Why:** Old graph neighborhoods are no longer semantically meaningful.

#### 2. Index Build Parameters Changed
Rebuild if ANY of these change:
- `m` (bi-directional links per node)
- `ef_construction` (candidate set size during build)
- Quantization/compression mode
- Engine version that changes graph format

**Why:** These are construction-time properties; cannot modify existing graph.

#### 3. Partitioning/Sharding Changes
Rebuild if:
- Bucket count changes (256 → 1024)
- Tenant routing rules change
- Shard split/merge/rebalance occurs

**Why:** Data must move across indices; clean build needed in new layout.

### Conditional Rebuild Triggers

#### 4. High Deletion Rate
Rebuild when:
- Tombstones/deleted entities > 10% of total nodes
- (Deletes + updates) per day > 1-5% of index consistently
- p95 latency drifts upward despite tuning `ef_search`

**Why:** Graph accumulates dead nodes; search must work harder.

#### 5. Large Bulk Ingest
Rebuild when:
- New vectors since last rebuild > 25-40% of index size

**Why:** Incremental inserts can be suboptimal vs fresh balanced build.

#### 6. Quality Regression
Rebuild when monitoring shows:
- Recall@K drops beyond tolerance
- Reranker scores fall systematically
- "Couldn't find it" feedback increases
- p95/p99 latency exceeds SLO

**Why:** This is the truth-based trigger; best indicator of real problems.

### Do NOT Rebuild For:
- Steady appends (incremental inserts are fine)
- Different `ef_search` (query-time parameter)
- Adding new metadata fields (unless routing changes)
- Small deletion rates (< few %)
- Normal operational insert/update patterns

---

## Background Reindex + Atomic Swap Pattern

### Gold Standard: Shadow Index + Dual-Write + Alias Swap

**Process:**

1. **Start Build B**
   - Create new index `entity_embeddings_index_b`
   - Build from snapshot of all live vectors
   - Use same parameters as Index A

2. **Dual-Write Period**
   - All new inserts/updates/deletes write to BOTH A and B
   - Background job continues building B

3. **Delta Sync**
   - When B build catches up, sync events since build start
   - Continue until lag = 0

4. **Validation**
   - Counts match (live vectors in A vs B)
   - Sampling queries: compare latency/recall
   - Ensure no quality regression

5. **Atomic Swap**
   - Flip pointer/alias from A → B in one transaction
   - All queries immediately use B

6. **Cleanup**
   - Keep A briefly for rollback capability
   - Delete A after confidence period (e.g., 24 hours)

### Atomic Swap Implementation Options

#### Option 1: Index Alias (Postgres)
```sql
-- Create alias pointing to current active index
CREATE VIEW entity_embeddings_active AS
SELECT * FROM entity_embeddings_index_b;  -- Change this atomically

-- Or use a config table
UPDATE index_config 
SET active_index = 'entity_embeddings_index_b'
WHERE index_name = 'entity_embeddings';
```

#### Option 2: Application-Level Pointer
```python
# Config table with strongly consistent reads
class IndexConfig(Base):
    index_name: str = "entity_embeddings"
    active_index_version: str = "a"  # or "b"
    
# Query routing
active_version = db.get(IndexConfig).active_index_version
index_name = f"entity_embeddings_index_{active_version}"
```

#### Option 3: pgvector Partition Swap
```sql
-- If using table partitioning
ALTER TABLE entity_embeddings
DETACH PARTITION entity_embeddings_index_a;

ALTER TABLE entity_embeddings
ATTACH PARTITION entity_embeddings_index_b;
```

### Operational Policy

**Immediate Rebuild On:**
- Embedding model change
- Index parameter change
- Partitioning/sharding change

**Schedule Rebuild When ANY Occurs:**
- Tombstones > 10% of total
- New vectors since last rebuild > 30%
- p95 latency > SLO (or rising trend) AND `ef_search` tuning exhausted

**Monitoring:**
- Track index size, tombstone count, query latency
- Alert on quality regression (recall@K, user feedback)
- Automated rebuild scheduling when thresholds crossed

---

## Query-Time Optimization

### ef_search Tuning

**Default:** `ef_search = 100`

**Tune based on:**
- **Low latency requirement (< 50ms)**: `ef_search = 40-60`
- **High recall requirement (> 95%)**: `ef_search = 200-300`
- **Balanced (default)**: `ef_search = 100`

**Per-Query Override:**
```sql
SET LOCAL hnsw.ef_search = 200;  -- For this query only
SELECT ...
```

**Monitoring:**
- Track recall@K vs latency tradeoff
- Adjust based on tenant requirements (strict vs lenient screening)

### Filter Optimization

**Best Practice:**
1. Apply tenant filter EARLY (in WHERE clause)
2. Use index on `(tenant_id, source_list)` for fast filtering
3. Let pgvector handle vector search efficiently within filtered set

**Query Pattern:**
```sql
-- Good: Filter first, then vector search
WITH filtered_entities AS (
    SELECT entity_id, embedding
    FROM entity_embeddings ee
    JOIN entities e ON e.entity_id = ee.entity_id
    WHERE (e.tenant_id = $1 OR e.tenant_id IS NULL)
      AND e.source_list = ANY($2)
)
SELECT entity_id, embedding <=> $3 AS distance
FROM filtered_entities
ORDER BY distance
LIMIT $4;

-- Bad: Vector search first, filter after (wastes work)
SELECT entity_id, embedding <=> $3 AS distance
FROM entity_embeddings
ORDER BY distance
LIMIT 1000  -- Too many
WHERE tenant_id = $1;  -- Then filter (inefficient)
```

---

## Multi-Tenant Isolation Guarantees

### Application-Level Isolation (OSS Mode)
- All queries include `WHERE tenant_id = X OR tenant_id IS NULL`
- Application ensures tenant_id from auth context (never from payload)
- Global entities (`tenant_id IS NULL`) visible to all
- Tenant custom entities (`tenant_id = X`) only visible to tenant X

### Database-Level Isolation (SaaS Mode)
- Row Level Security (RLS) policies enforce tenant_id
- Set tenant context: `SET LOCAL app.tenant_id = 'acme'`
- RLS automatically filters all queries
- Zero risk of cross-tenant data leakage

### Vector Search Isolation
- Vector search happens on filtered dataset
- Post-filter ensures tenant isolation
- Metadata fields (`tenant_id`, `source_list`) stored with embeddings
- Index design supports efficient filtered ANN

---

## Scaling Guidelines

### Tenant Count → Strategy Mapping

| Tenants | Recommended Strategy | Notes |
|---------|---------------------|-------|
| < 50K | Single Global HNSW + Filter | Simple, efficient for shared lists |
| 50K - 5M | Bucketed HNSW (256-1024 buckets) | Better isolation, predictable latency |
| 5M+ | Bucketed + Two-Tier Hot/Cold | Optimize for recent data access |

### Vector Count → Index Strategy

| Vectors/Index | Action |
|---------------|--------|
| < 1M | Single index fine |
| 1M - 10M | Consider bucketing if latency issues |
| 10M+ | Bucket or partition required |

### Consumer performance targets (guidance, not a library SLA)

These targets describe a production backend an adopter may choose to operate;
`edgeproc-core` does not ship that HNSW service or claim its latency. The
repeatable benchmark for library-owned routing and the in-memory reference lives
in [`OPERATIONS.md`](OPERATIONS.md).

- **Query Latency (p95)**: < 100ms
- **Recall@20**: > 95%
- **Index Build Time**: < 30min for 100K entities
- **Index Size**: Monitor memory usage per index

---

## Migration & Rollout

### Phase 1: Initial Deployment
- Single global HNSW index
- Metadata filtering
- Monitor query performance

### Phase 2: Scale Assessment
- Measure tenant growth
- Monitor index size and query latency
- Collect tenant distribution data

### Phase 3: Migration to Bucketing (if needed)
1. Design bucket strategy (256 vs 1024)
2. Implement bucket_id computation
3. Build new indices in background
4. Dual-write during migration
5. Atomic swap
6. Monitor and validate

---

## Monitoring & Alerting

### Key Metrics

**Index Health:**
- Index size (vectors, memory)
- Tombstone percentage
- Build time
- Build frequency

**Query Performance:**
- p50/p95/p99 latency
- Recall@K (sampled queries)
- Query volume per tenant
- Error rate

**Quality:**
- Reranker score trends
- User feedback ("not found" reports)
- Match rate trends

### Alerting Thresholds

- **Latency**: p95 > 200ms for > 5min
- **Recall**: Recall@20 < 90% for sampled queries
- **Index Size**: Individual index > 10M vectors
- **Tombstones**: > 10% of index
- **Build Time**: > 1 hour

---

## References

- pgvector HNSW documentation
- Multi-tenant vector search patterns
- HNSW algorithm papers
- Production scaling experiences

---

**Document Version**: 1.1
**Last Updated**: 2026-07-15
**Status**: Consumer architecture guidance; shipped code is the typed partitioning protocol

**Library**: `~/dev/edgeproc-core`
**Package**: `edgeproc_core.vector_mgmt`
