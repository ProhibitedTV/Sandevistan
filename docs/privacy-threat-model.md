# Privacy Threat Model

## Scope and assumptions
- This document covers privacy risks and mitigations for data processed by the system, including any telemetry, logs, and user-provided inputs.
- The system must minimize collection, storage, and sharing of personal or sensitive data.

## Data collection boundaries

### Who is tracked
- **End users**: Any person interacting with the product or whose data is provided to the system.
- **Administrators/operators**: Personnel who access operational dashboards, logs, or analytics.
- **Bystanders**: Individuals who may appear in data streams (e.g., incidental capture) but are not direct users.

### Consent requirements
- **Explicit consent** is required before collecting or processing any personal data beyond what is strictly necessary for core functionality.
- **Opt-in only** for analytics or telemetry that is not essential to service delivery.
- **Contextual notice** must be provided where collection occurs, describing what is collected and why.
- **Revocation**: Users must be able to withdraw consent, which stops collection and triggers deletion workflows where feasible.

### Retention policies
- **Default minimal retention**: Keep personal data only as long as required to deliver the service.
- **Time-bounded retention**: Define retention windows per data category (e.g., logs, telemetry, user content).
- **Automated deletion**: Data must be deleted or anonymized when retention windows expire or consent is withdrawn.
- **Backup handling**: Backups containing personal data must follow the same retention and deletion requirements.

## Threats

### Unauthorized surveillance
- Covert tracking of users or bystanders without consent.
- Inference of sensitive attributes or behaviors from benign data.
- Correlation of identifiers across datasets to build profiles.

### Data leaks
- Exposure of personal data through insecure storage, misconfigured access, or accidental publication.
- Leakage via logs, analytics, or debugging artifacts.
- Breaches of third-party services used for storage or processing.

### Misuse by operators
- Insider access to sensitive data beyond operational need.
- Use of data for purposes outside the stated scope (function creep).
- Inadequate segregation of duties leading to abuse.

## Mitigations

### On-device processing
- Perform analysis locally whenever feasible to avoid transmitting raw personal data.
- Use privacy-preserving defaults that minimize data sent off-device.

### Anonymization and minimization
- Collect only data required for specific, documented purposes.
- Apply aggregation, hashing, or differential privacy to reduce identifiability.
- Strip or tokenize identifiers before storage or sharing.

### Access controls
- Enforce least-privilege access for operators and services.
- Use strong authentication, role-based access control, and periodic access reviews.
- Segregate production data from development and testing environments.

### Audit logging
- Log access to sensitive data with sufficient detail for accountability.
- Protect audit logs against tampering and ensure retention for compliance.
- Regularly review audit logs for anomalies.

## Release checklist (must be satisfied before launch)
- [ ] Data collection inventory completed and approved.
- [ ] Consent flows implemented and tested, including revocation handling.
- [ ] Retention windows defined per data category and automated deletion verified.
- [ ] On-device processing used where feasible; data flows reviewed for minimization.
- [ ] Anonymization or aggregation applied before storage or analytics.
- [ ] Access controls enforced with least privilege and periodic reviews scheduled.
- [ ] Audit logging enabled and protected against tampering.
- [ ] Incident response plan includes privacy breach procedures.
- [ ] Third-party processors reviewed for privacy and security compliance.
- [ ] Privacy impact assessment completed and signed off.
