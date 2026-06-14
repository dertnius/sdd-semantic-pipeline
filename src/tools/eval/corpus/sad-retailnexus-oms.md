---
title: "RetailNexus OMS – Software Architecture Document"
space: "ARCH"
source_file: "SAD_RetailNexus_OMS_Confluence.html"
---

### 📋 Document Properties

|  |  |
|----|----|
| Document Title | Software Architecture Document (SAD) – RetailNexus Order Management System |
| Project | RetailNexus Platform Modernisation – PI-11 |
| Document Version | 2.3 |
| Status | `Approved` |
| SDLC Phase | Architecture & Design (Agile PI Planning – PI-11, Sprint 3) |
| Author(s) | Marcus Sandoval (Principal Architect), Priya Nair (Solutions Architect) |
| Reviewer(s) | CTO Office, Security Guild, Platform Team Lead |
| Date Approved | 12 November 2025 |
| Next Review | Q1 2026 (post PI-12 planning) |
| Confluence Space | ARCH / OMS Platform |
| Jira Epic | [RETL-1042](#) · [RETL-1088](#) |

> ⚠️ **WARNING**: Sections 7 (Security) and 10 (Risk Register) are pending final sign-off from the Security Guild. All other sections are approved. Do not distribute externally until final approval is recorded.

# Introduction

## Purpose

This Software Architecture Document (SAD) describes the technical architecture of the **RetailNexus Order Management System (OMS)**, a cloud-native microservices platform that handles end-to-end order lifecycle management for the RetailNexus e-commerce ecosystem. The document is authored in accordance with the **Agile SDLC** adopted by the organisation, and serves as the canonical architectural reference throughout PI-11 and subsequent increments.

The SAD is intended to:

- Define and communicate key architectural decisions to all stakeholders
- Provide a stable baseline for Sprint-level design and implementation work
- Serve as input to Component-level Software Design Documents (SDDs)
- Enable Architecture Review Board (ARB) assessment of fit-for-purpose

## Scope

This document covers the architectural design of all services comprising the OMS platform boundary, including:

- Order ingestion, validation, and processing pipeline
- Inventory reservation and fulfillment orchestration
- Payment processing integration (card, BNPL, wallet)
- Carrier & 3PL integration for last-mile logistics
- Customer notification and order-tracking experience
- Reporting, audit, and operational dashboards

> ℹ️ **INFO**: This document does not cover the Product Catalogue, CRM, or ERP integrations beyond defined interface contracts. Those are addressed in their respective SAD documents (see sidebar links).

## Definitions & Acronyms

| Term / Acronym | Definition |
|----|----|
| `OMS` | Order Management System — the primary system described in this document |
| `PI` | Program Increment — SAFe planning cadence (typically 10 weeks) |
| `ARB` | Architecture Review Board |
| `ADR` | Architecture Decision Record |
| `3PL` | Third-Party Logistics provider |
| `BNPL` | Buy Now Pay Later |
| `SLO` | Service Level Objective |
| `PII` | Personally Identifiable Information |
| `CQRS` | Command Query Responsibility Segregation |
| `EDA` | Event-Driven Architecture |
| `mTLS` | Mutual Transport Layer Security |

# System Overview

## Business Context

RetailNexus processes **~4.2 million orders per month** across web, mobile, and marketplace channels. The current monolithic OMS (legacy COBOL/Oracle stack, circa 2009) cannot support projected growth targets of 15× peak throughput for the Q4 2026 Black Friday event, nor does it meet the organisation's cloud-first and API-first strategic mandates.

The replacement platform must support multi-tenancy for three business units (B2C, B2B, Marketplace) and expose a unified Order API consumed by over 60 downstream integrations.

## System Context Diagram

------------------------------------------------------------------------

📊 *Figure 1 — C4 Level 1: System Context Diagram – RetailNexus OMS Platform*

> ⚙️ Diagram: SVG rendered in source document. Attach an exported image or replace with a Mermaid diagram block.

------------------------------------------------------------------------

# Architecture Goals & Constraints

## Quality Attribute Requirements

| Quality Attribute | Requirement | Measure / SLO | Priority |
|----|----|----|----|
| **Performance** | Order creation API must respond within SLO under peak load | p95 < 300ms, p99 < 800ms | `Critical` |
| **Scalability** | Must sustain 15× baseline throughput for Q4 peak | ≥ 8,000 orders/min sustained | `Critical` |
| **Availability** | Order processing pipeline availability | 99.95% monthly uptime | `Critical` |
| **Resilience** | Graceful degradation when downstream services unavailable | Circuit breaker + fallback within 2s | `High` |
| **Security** | PCI-DSS Level 1 compliance for payment flows | Zero card data in OMS storage | `Critical` |
| **Observability** | Full distributed tracing across all services | 100% trace coverage, MTTD < 5min | `High` |
| **Maintainability** | Independent service deployability | Deploy any service in < 15 min with zero downtime | `Medium` |
| **Data Integrity** | Idempotent order processing, no duplicate charges | Exactly-once semantics for payment events | `Critical` |

## Architectural Constraints

- **Cloud:** AWS (primary) — all compute must run on EKS; no on-premises compute for new services
- **Language:** Backend services in Java 21 (Spring Boot 3.x) or Go 1.22; no new Node.js backend services
- **Database:** PostgreSQL (Aurora) for OLTP; no shared databases between microservices
- **Messaging:** Apache Kafka (MSK) as the enterprise event bus; SQS permitted for async fan-out
- **API Style:** REST (OpenAPI 3.1) for synchronous; AsyncAPI 2.x for event contracts
- **Auth:** OAuth 2.0 / OIDC via Okta; service-to-service via mTLS + SPIFFE/SPIRE
- **Compliance:** PCI-DSS Level 1, GDPR, ISO 27001

# Component Architecture

## Architectural Style

The OMS adopts an **Event-Driven Microservices** architectural style with the following key patterns:

- **CQRS** — Commands (writes) and Queries (reads) are handled by separate models and service paths
- **Saga Pattern** — Distributed transactions across services orchestrated via Choreography-based Sagas over Kafka
- **Outbox Pattern** — Transactional outbox ensures at-least-once event delivery without distributed transactions
- **API Gateway** — Single ingress for all external consumers; handles auth, rate-limiting, and routing
- **BFF (Backend for Frontend)** — Dedicated aggregation layer for Web and Mobile channels

## High-Level Component Diagram

------------------------------------------------------------------------

📊 *Figure 2 — C4 Level 2: Container Diagram – OMS Platform*

> ⚙️ Diagram: SVG rendered in source document. Attach an exported image or replace with a Mermaid diagram block.

------------------------------------------------------------------------

## Microservices Inventory

| Service | Language | Owns DB | Exposes | SDD Link | Status |
|----|----|----|----|----|----|
| `order-service` | Java 21 | Aurora PG (orders) | REST + Events | [SDD-OMS-01](#) | `Live` |
| `inventory-service` | Java 21 | Aurora PG (inventory) | REST + Events | [SDD-OMS-02](#) | `Live` |
| `payment-service` | Go 1.22 | Aurora PG (payment) | REST + Events | [SDD-OMS-03](#) | `Live` |
| `fulfillment-service` | Java 21 | Aurora PG (fulfillment) | REST + Events | [SDD-OMS-04](#) | `In Progress` |
| `notification-service` | Go 1.22 | None (stateless) | Events (consume only) | [SDD-OMS-05](#) | `Live` |
| `saga-orchestrator` | Java 21 | DynamoDB (state) | Internal only | [SDD-OMS-06](#) | `In Progress` |
| `reporting-service` | Java 21 | OpenSearch (read model) | REST (read-only) | [SDD-OMS-07](#) | `Planned` |
| `audit-service` | Go 1.22 | DynamoDB (events) | REST (read-only) | [SDD-OMS-08](#) | `Planned` |
| `bff-web` | Java 21 | None | GraphQL | [SDD-OMS-09](#) | `Live` |
| `bff-mobile` | Go 1.22 | None | GraphQL | [SDD-OMS-10](#) | `Live` |

# Integration Architecture

## External Integration Contracts

| System | Protocol | Direction | Trigger | SLA |
|----|----|----|----|----|
| Stripe / Adyen (Payment) | REST / Webhooks | OMS → Provider, Provider → OMS | Checkout, Refund | p99 < 2s |
| SAP WM (Inventory) | REST (OData v4) | Bidirectional | Reservation, Release | p95 < 500ms |
| FedEx / DHL / UPS | REST | OMS → Carrier | Shipment Create, Cancel | p95 < 1s |
| SendGrid / AWS SNS | REST / SDK | OMS → Provider | Order events (Kafka consume) | Fire-and-forget |
| SAP S/4HANA (ERP) | IDOC / RFC over MQ | OMS → ERP | Invoice trigger on ship | Async < 5min |

## Kafka Topic Registry

```yaml
# Retention: 7 days  |  Replication: 3  |  Partitions: per throughput estimate

topics:
  order.created:           # Published by order-service
    partitions: 24
    key:        orderId   # ensures ordering per order
    consumers: [inventory-service, payment-service, notification-service, audit-service]

  order.paid:               # Published by payment-service
    partitions: 24
    consumers: [fulfillment-service, notification-service, audit-service]

  order.cancelled:           # Published by order-service or saga-orchestrator
    partitions: 12
    consumers: [inventory-service, payment-service, notification-service]

  inventory.reserved:       # Published by inventory-service
    partitions: 12
    consumers: [saga-orchestrator]

  payment.authorised:       # Published by payment-service
    partitions: 24
    key:        paymentId
    consumers: [order-service, saga-orchestrator]

  fulfillment.shipped:       # Published by fulfillment-service
    partitions: 12
    consumers: [order-service, notification-service, reporting-service]
```

# Data Architecture

## Database-per-Service Strategy

> ℹ️ **INFO**: Each microservice owns its data exclusively. No service may query another service's database directly. Cross-service data access is achieved only via published events (Kafka) or synchronous API calls. This enforces loose coupling and independent deployability.

## Order Data Model (Core Entity)

```sql
CREATE TABLE orders (
  id              UUID          PRIMARY KEY   DEFAULT gen_random_uuid(),
  tenant_id       UUID          NOT NULL,                      -- B2C | B2B | Marketplace
  customer_id     UUID          NOT NULL,
  channel         VARCHAR(20)  NOT NULL,                      -- WEB | MOBILE | API
  status          VARCHAR(30)  NOT NULL DEFAULT 'PENDING',   -- FSM state
  currency        CHAR(3)      NOT NULL DEFAULT 'USD',
  subtotal        NUMERIC(12,2) NOT NULL,
  tax             NUMERIC(12,2) NOT NULL DEFAULT 0,
  shipping_total  NUMERIC(12,2) NOT NULL DEFAULT 0,
  total           NUMERIC(12,2) NOT NULL,
  idempotency_key UUID          NOT NULL UNIQUE,             -- prevents duplicates
  metadata        JSONB,
  created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_orders_customer   ON orders (customer_id, created_at DESC);
CREATE INDEX idx_orders_tenant_status ON orders (tenant_id, status);
CREATE INDEX idx_orders_outbox     ON orders (status) WHERE status = 'PENDING_EVENT';
```

## Order State Machine

| From State | Event | To State | Actor |
|----|----|----|----|
| — | `CreateOrder` | `PENDING` | Customer / API |
| `PENDING` | `inventory.reserved` | `INVENTORY_RESERVED` | Inventory Svc |
| `INVENTORY_RESERVED` | `payment.authorised` | `PAYMENT_AUTHORISED` | Payment Svc |
| `PAYMENT_AUTHORISED` | `fulfillment.created` | `IN_FULFILLMENT` | Fulfillment Svc |
| `IN_FULFILLMENT` | `fulfillment.shipped` | `SHIPPED` | Fulfillment Svc |
| `SHIPPED` | `fulfillment.delivered` | `DELIVERED` | Carrier webhook |
| Any non-terminal | `CancelOrder` | `CANCELLING` | Customer / Ops |
| `CANCELLING` | `saga.compensated` | `CANCELLED` | Saga Orchestrator |

# Security Architecture

> ⚠️ **WARNING**: This section is under review by the Security Guild (ticket: SEC-482 ). Target approval: 28 Nov 2025.

## Authentication & Authorisation

- **External clients** authenticate via Okta (OAuth 2.0 / OIDC). JWTs are validated at the API Gateway; downstream services receive forwarded claims.
- **Service-to-service** communication is secured using mTLS with SPIFFE/SPIRE for workload identity. No long-lived credentials shared between services.
- **RBAC** is enforced at the API Gateway layer via Kong's OPA plugin. Fine-grained permissions are defined per endpoint and tenant.

## PCI-DSS Considerations

> 📝 **NOTE**: The OMS is intentionally out of PCI scope . Card data never touches OMS storage or logs. The payment-service tokenises card data via the provider SDK before any API call leaves the client browser (Stripe.js / Adyen Web SDK). OMS stores only the resulting payment token and authorisation reference.

# Deployment Architecture

## AWS Infrastructure Overview

| Component | AWS Service | Config | Region |
|----|----|----|----|
| Container Orchestration | Amazon EKS 1.30 | 3 node groups (on-demand + Spot) | us-east-1 (primary), eu-west-1 (DR) |
| API Gateway | Kong on EKS + AWS APIGW | HA, 3 replicas min | Both regions |
| OLTP Database | Amazon Aurora PostgreSQL 15 | Multi-AZ, r6g.2xlarge writer | us-east-1 |
| Event Bus | Amazon MSK (Kafka 3.6) | 3 brokers, m5.2xlarge, TLS | us-east-1 |
| Cache | Amazon ElastiCache (Redis 7) | Cluster mode, 3 shards | us-east-1 |
| Search | Amazon OpenSearch 2.11 | 3 data nodes, m6g.large | us-east-1 |
| Object Storage | Amazon S3 | Versioned, encrypted at rest | Both regions |
| CDN | Amazon CloudFront | Edge caching for static assets | Global |
| Secrets | AWS Secrets Manager | Auto-rotation 30 days | Both regions |
| Observability | Datadog (APM + Logs + Tracing) | Full coverage, 15-day retention | SaaS |

## CI/CD Pipeline

```yaml
name: OMS Service CI/CD

on:
  push:
    branches: [main, 'release/**']
  pull_request:
    branches: [main]

jobs:
  build-test:
    steps:
      # Unit tests (JUnit / testify) + code coverage gate ≥ 80%
      - run: ./gradlew test jacocoReport
      # Static analysis + security scan
      - uses: sonarcloud/sonarcloud-github-action@v2
      - uses: snyk/actions/gradle@master
      # Build and push image
      - run: docker build -t $ECR_REGISTRY/$SERVICE:$SHA .
      - run: docker push $ECR_REGISTRY/$SERVICE:$SHA

  deploy-staging:
    needs: build-test
    steps:
      - run: helm upgrade --install $SERVICE ./helm --set image.tag=$SHA -n staging
      - run: kubectl rollout status deployment/$SERVICE -n staging --timeout=300s
      # Contract tests (Pact) against staging provider
      - run: ./gradlew pactVerify

  deploy-prod:
    needs: deploy-staging
    environment: production   # requires manual approval
    steps:
      # Blue/green deploy via Argo Rollouts
      - run: kubectl argo rollouts set image $SERVICE $SERVICE=$ECR_REGISTRY/$SERVICE:$SHA -n prod
      - run: kubectl argo rollouts promote $SERVICE -n prod
```

# Architecture Decision Records

#### ADR-001 — Adopt Event-Driven Architecture with Apache Kafka as the Enterprise Event Bus

**Status:** Accepted

**Context:** The OMS must coordinate state changes across 10+ independent services with high throughput, at-least-once delivery guarantees, and support for event replay for new consumers.

**Decision:** Use Apache Kafka (Amazon MSK) as the enterprise event bus. All domain events are published to Kafka topics. Services consume events asynchronously. The Outbox Pattern is used to guarantee transactional event publication.

**Consequences:** **+** Decoupled services, event replay, high throughput. **−** Increased operational complexity; team requires Kafka expertise. **Alternatives rejected:** Amazon SQS/SNS (no replay, limited ordering), RabbitMQ (lower throughput ceiling).

#### ADR-002 — Use CQRS with Separate Read and Write Models for Order Queries

**Status:** Accepted

**Context:** Order search and reporting queries require flexible filtering, full-text search, and aggregation that Aurora PostgreSQL cannot serve efficiently at scale without hurting write performance.

**Decision:** The write model (commands) is served by Aurora PostgreSQL. The read model is materialised to Amazon OpenSearch via a Kafka consumer in `reporting-service`. Clients issuing read queries hit OpenSearch exclusively.

**Consequences:** **+** Query flexibility, no read load on OLTP DB. **−** Eventual consistency on read model (~100ms lag). Acceptable per business requirements. **Alternatives rejected:** PostgreSQL read replicas (limited search capability).

#### ADR-003 — Choreography-Based Saga for Distributed Order Transactions

**Status:** Accepted

**Context:** Order placement involves inventory reservation, payment authorisation, and fulfillment creation — all in separate services with no shared transaction boundary.

**Decision:** Implement a Choreography Saga: each service reacts to domain events and publishes its own. Compensation (rollback) is triggered by `saga-orchestrator` via Temporal.io when a step fails after a configurable retry policy.

**Consequences:** **+** No single point of failure in orchestration logic. **−** Complex debugging requires full distributed tracing. Mitigated by mandatory Datadog APM coverage.

View additional ADRs (ADR-004 through ADR-009)

| ADR | Title | Status | Date |
|----|----|----|----|
| `ADR-004` | Database-per-Service with no shared schema | `Accepted` | Mar 2025 |
| `ADR-005` | Kong as API Gateway over AWS APIGW | `Accepted` | Apr 2025 |
| `ADR-006` | Use mTLS + SPIFFE/SPIRE for service identity | `Accepted` | May 2025 |
| `ADR-007` | Temporal.io for Saga compensation workflow | `Accepted` | Jul 2025 |
| `ADR-008` | Blue/Green deployments via Argo Rollouts | `Accepted` | Aug 2025 |
| `ADR-009` | GraphQL BFF pattern for Web and Mobile | `Under Review` | Oct 2025 |

# Risk Register

| ID | Risk | Probability | Impact | Rating | Mitigation | Owner |
|----|----|----|----|----|----|----|
| `RSK-01` | Kafka consumer lag causes order processing delay during peak | Medium | High | HIGH | Auto-scaling consumer groups via KEDA; lag-based HPA configured at ≥ 5,000 msgs lag | Platform Team |
| `RSK-02` | Aurora failover during order creation causes data loss | Low | Critical | HIGH | Outbox pattern + idempotency keys guarantee at-least-once; Aurora Multi-AZ failover < 30s | DBA / Order Team |
| `RSK-03` | Stripe API rate limiting during Black Friday burst | Medium | High | HIGH | Pre-negotiated Stripe rate limit uplift; Adyen as hot standby; circuit breaker with fallback to queue | Payment Team |
| `RSK-04` | Team Kafka expertise gap slows incident MTTR | High | Medium | MEDIUM | Q3 2025 Kafka training completed; on-call runbook published; Confluent Support contract active | Engineering Manager |
| `RSK-05` | GDPR right-to-erasure conflicts with event sourcing immutability | Medium | Medium | MEDIUM | PII separated to dedicated vault; events store PII reference tokens only; erasure deletes vault entry (crypto-shredding) | Privacy Team |
| `RSK-06` | SAP WM integration latency degrades inventory reservation SLO | Low | Medium | LOW | Local inventory cache (Redis) with 60s TTL; async reconciliation via background job | Integration Team |

# Open Issues & Action Items

| ID | Issue | Type | Owner | Due | Status |
|----|----|----|----|----|----|
| [ARCH-201](#) | Finalise data retention policy for Kafka topics (GDPR alignment) | Decision | Privacy + Arch | 28 Nov 2025 | `In Progress` |
| [ARCH-207](#) | ADR-009 GraphQL BFF — resolve schema stitching vs federation debate | Decision | API Guild | 05 Dec 2025 | `In Progress` |
| [ARCH-215](#) | Confirm OpenSearch index strategy for cross-tenant order search | Design | Search Team | 12 Dec 2025 | `Not Started` |
| [ARCH-220](#) | Load test results for 8,000 orders/min target (PI-11 Sprint 4) | Validation | Platform Team | 19 Dec 2025 | `Not Started` |
| [SEC-482](#) | Security Guild sign-off on Section 7 (mTLS key rotation policy) | Approval | Security Guild | 28 Nov 2025 | `In Progress` |

> ✅ **TIP**: All SDD authors should reference this SAD as the authoritative architectural baseline. Any deviation from the patterns defined here must be raised as an ADR and approved by the ARB before implementation. Contact @marcus.sandoval or post in \#architecture Slack channel.
