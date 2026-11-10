# Repository instructions

## Owner-approved II-1 acceptance — 2026-10-31

Accepted II-T06/T08 add an explicit bounded durable crop-health v1 sink/DLQ and generated-only verify_crop_health.py, retaining 3A/3B/WA-1 checks. Use exclusively new disposable projects and generated fixtures/credentials; preserve existing data/volumes/realm. No running-stack/role/credential/production/Git/AEO mutation. II-D07/08 and WA D08/D09 remain open. See Architecture INCIDENT_INSPECTION_CONTRACT_APPROVAL.md.

Work only within this independent Git repository. No parent repository, submodules, shared persistence models, cross-service SQL or multi-service Maven parent.

Current scope: Milestone 1C shared local infrastructure, identity, broker/tracing configuration and platform acceptance. Preserve service-owned migrations and independent application builds.

Use ports/adapters and service-owned migrations. APIs and events are designed in agrosphere-contracts; coordinate breaking changes through a versioned contract release, never a source path dependency. UUID estateId/blockId remain stable across clients. Mark data REAL, SIMULATED, ESTIMATED or PREDICTED. GeoJSON is WGS84 longitude/latitude (RFC 7946). Procedural trees are illustrative.

Never commit credentials, local environment files, generated datasets or large geospatial assets. Use environment examples containing placeholders only. No remote creation, push or cloud deployment is authorized.

Run repository checks documented in README.md. Report actual checks separately from unavailable checks. Version independently using SemVer and CHANGELOG.md; changes to 0.x contracts can still break consumers and require review.

## Scoped credential-wiring authorization - 2026-10-27

The owner authorizes the reviewed Operations-only runtime/Flyway wiring, tracked placeholders and provisioning-tool implementation, and generated credentials only in disposable tests. This supplements earlier secret-handling exclusions only for that scope. Do not read/modify existing private environment files, provision existing/running stacks, or change production/AEO state. See Architecture docs/milestones/MILESTONE_3B_CREDENTIAL_WIRING_APPROVAL.json and continue authorized T03-T09 in dependency order.

## Owner-authorized WA-1 — 2026-10-29

The accepted WA-1 scope adds a bounded durable workforce v1 sink and generated-only scripts/verify_workforce.py, retaining 3A/3B checks. Run only new disposable projects, never the existing developer stack or realm. D08 workload/rollout and D09 privacy/retention remain gates. No REAL worker data, commit/push/publish, production/destructive migration, existing-stack/private-environment or AEO change is authorized.

## AN-1 exact executable accepted — 2026-10-31

Architecture ALERTS_NOTIFICATIONS_CONTRACT_APPROVAL.md records owner acceptance of the exact four artifacts, local Contracts 0.8.0 release and Operations/Web pins. Continue accepted AN-T03–09 by dependency; preserve prior features/artifacts and reviewed bytes. Generated-only verification; AN-D07/08 and WA/II/M2 gates remain open. No non-generated account rollout, REAL, existing-stack/private configuration/role/credential/external delivery/Git/deployment/destructive/data-reset/AEO action. Gateway adds only /api/v1/alerts/**; Infrastructure generated-only drills reuse existing topology without a new alert queue.

## AN-1 local verification state — 2026-10-31

Architecture ALERTS_NOTIFICATIONS_VERIFICATION.md records local implementation and generated-only checks after exact executable acceptance. Earlier preparation labels are historical. Preserve 0.8.0 pins/old bytes/V1–V5/Web config/index and existing data/volumes. Default-disabled subject-policy gate, AN-D07/08, WA/II/M2 and no non-generated rollout/REAL/live-stack/private configuration/role/credential/Git/deployment/AEO exclusions remain.

## Owner-approved AN privacy extension — 2026-10-31

Architecture ALERTS_PRIVACY_APPROVAL.md records exact five-artifact privacy candidate acceptance (manifest ea6402a205d1da7a0801090b0acabac58ae164ba6544b474d709d8a4a608286b), local independent Contracts 0.9.0 release/archive/pins and generated-only AP-T02–07 implementation. Preserve accepted bytes, V1–V6, old events/records and all staged work/Web config. Additive privacy storage and narrowly scoped maintenance may be tested only in separately owned disposable generated databases. No existing-stack/private configuration/actual-account/REAL/existing role or credential/destructive migration/historical conversion/external delivery/Git publication/deployment/AEO action. AP-T08 local-stack execution remains separately gated; do not repeat II-1. Prior approval/pending labels remain historical within their scope; do not ask again for this exact acceptance.


## TLM-01 adapters authorized — 2026-11-01

Architecture MQTT_POC_ADAPTER_APPROVAL.md accepts exact package 389f1d3cfa6ca80fd602c2f945b9f23965723b53d5ca169919f7e11099e2bc75. Implement Telemetry SIMULATED ingestion/persistence/outbox/latest API, Gateway telemetry route only and Infrastructure generated-only owned disposable drills. Exact SQL/ACL/client engineering review and generated fixture credentials included. No repeated domain/executable approval. Preserve Contracts 0.10.0 pins, old migrations/config/data/indexes, existing stacks/private config/roles/credentials, REAL/Git/deployment/AEO exclusions.


## Owner-approved TLM-02 — 2026-11-04

Architecture MQTT_POC_OVERLAY_APPROVAL.md accepts exact review 0d8a67aef15b295dbca267adad300ab0c94c2c88ec37cbff0c6a69c1ff7a49c9. Implement bounded deterministic SIMULATED fixture publisher and read-only selected-block Web detail/freshness overlay using unchanged Contracts 0.10.0 pin. Generated-only disposable verification, no new schema/role, no repeated executable approval. Preserve existing UI/config/index/data and all original gates; no existing-stack/private config/REAL/production/Git/deployment/AEO action.


## ANL-01 bounded runtime continuation — 2026-11-05

Owner instructed "please resume" immediately after the bounded runtime/dashboard approval request. Architecture ANALYTICS_POC_ADAPTER_APPROVAL.md records that continuation authority for exact review 855fe1894c530cf7942d3175e7a3eae850d0b34abff976a5e6bf7ba87a5618f3: SIMULATED materialized Analytics, Analytics-only Gateway route, read-only Web dashboard and new owned disposable verification. Existing 0.11.0 contracts/pins unchanged; exact SQL/grant engineering review precedes new-fixture installation. No existing-stack/private config/data/roles/credentials, REAL, production/Git/deployment/AEO action. Preserve indexes/prior features and original owner/field/milestone gates.


## ANL-01 finite admission approved

Owner approved exact admission review SHA-256 5c9a6787f0ebf2ad0d3d172e5fc3ac2ebb9d83ea9936c3664331fa81fe8629f8. Architecture ANALYTICS_POC_ADMISSION_APPROVAL.md records finite generated profile, bounded parser/diagnostic/test changes and new owned disposable verification. Prior approvals satisfied; preserve exact contracts, migrations, indexes/private config/data and all owner/field/REAL/AEO/Git/deployment exclusions.


## ANL-02 bounded runtime approved — 2026-11-05

Architecture ANALYTICS_ENVIRONMENT_ADAPTER_APPROVAL.md records owner acceptance of exact runtime/SQL manifest afff8ff5a13e1167d53ab569f0ea28c5f003def01fab9318db455f291f537ea8. Implement SIMULATED environmental parser/immutable persistence/consumer/scoped API, read-only Web with independent 0.12.0 pin and new owned disposable verification; generated fixture credentials included. Exact SQL/grant engineering review before installation. No new producer/role or Gateway prefix widening. Preserve old artifacts/V1/V2/config/data/index and all original gates. No existing-stack/private config/account/role/credential, REAL, Git publication/deployment or AEO action. Historical pending labels are superseded only for this scope.


## Owner-approved exclusive M4 delivery — 2026-11-09

Owner approved Architecture M4_DELIVERY_PACKAGE.md revision 1, SHA-256 befbee78062c2fcef6af0ea394fcc81be3e7638053deca142f136c66bc7cc93d; exact response is in M4_DELIVERY_APPROVAL_2026_11_09.json. D01–D10/E01–E10 authorize the bounded observed dry/wet forecast/anomaly, immutable registry/evaluation, deterministic evidence composer, scoped API/UI and new owned generated verification, including conforming delegated local Contracts release/pins/SQL gates. No repeated owner approval for these gates. Preserve prior reviewed bytes, work/data/private config and repository independence. No production/Git publication/REAL/AEO or existing-target action. Engineering results and OPEN owner functional acceptance are in Architecture M4_DELIVERY_VERIFICATION_2026_11_10.md and the checkpoint. Work exclusively on the owner's named milestone; after M4 delivery, wait for the next milestone prompt. Historical foundation/no-AI/pending labels are superseded only for this approved scope.
