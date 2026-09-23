"""The initial cluster map (contract section 7).

Clusters group plugins by business coherence — this is a relationship graph,
not a permission or dependency hierarchy (contract section 6). The map is
extensible: new clusters are registered exactly like these, at runtime.
"""

from __future__ import annotations

from atlas_sdk import ClusterManifest

WORKFORCE_AND_TIME = "cluster.workforce_and_time"
WORKPLACE_AND_OPERATIONS = "cluster.workplace_and_operations"
MOBILITY_AND_FLEET = "cluster.mobility_and_fleet"
EMPLOYEE_FINANCE = "cluster.employee_finance"
EMPLOYEE_LIFECYCLE_AND_DEVELOPMENT = "cluster.employee_lifecycle_and_development"
EMPLOYEE_SERVICES_AND_RIGHTS = "cluster.employee_services_and_rights"
INFORMATION_AND_DOCUMENTS = "cluster.information_and_documents"
GOVERNANCE_AND_MANAGEMENT = "cluster.governance_and_management"

INITIAL_CLUSTERS: tuple[ClusterManifest, ...] = (
    ClusterManifest(
        cluster_id=WORKFORCE_AND_TIME,
        name="Workforce & Time",
        description="Attendance, leave, permission and overtime capabilities.",
    ),
    ClusterManifest(
        cluster_id=WORKPLACE_AND_OPERATIONS,
        name="Workplace & Operations",
        description="Workplace, field and workforce operations capabilities.",
    ),
    ClusterManifest(
        cluster_id=MOBILITY_AND_FLEET,
        name="Mobility & Fleet",
        description="Fleet operations and mobility integrations.",
    ),
    ClusterManifest(
        cluster_id=EMPLOYEE_FINANCE,
        name="Employee Finance",
        description="Employee finance and payroll capabilities.",
    ),
    ClusterManifest(
        cluster_id=EMPLOYEE_LIFECYCLE_AND_DEVELOPMENT,
        name="Employee Lifecycle & Development",
        description="Recruitment, onboarding, development and offboarding.",
    ),
    ClusterManifest(
        cluster_id=EMPLOYEE_SERVICES_AND_RIGHTS,
        name="Employee Services & Rights",
        description="HR service desk, employee rights and confidential cases.",
    ),
    ClusterManifest(
        cluster_id=INFORMATION_AND_DOCUMENTS,
        name="Information & Documents",
        description="Report studio, document exchange and cloud integrations.",
    ),
    ClusterManifest(
        cluster_id=GOVERNANCE_AND_MANAGEMENT,
        name="Governance & Management",
        description="Governance, administrative decisions, policy and management views.",
    ),
)

__all__ = [
    "EMPLOYEE_FINANCE",
    "EMPLOYEE_LIFECYCLE_AND_DEVELOPMENT",
    "EMPLOYEE_SERVICES_AND_RIGHTS",
    "GOVERNANCE_AND_MANAGEMENT",
    "INFORMATION_AND_DOCUMENTS",
    "INITIAL_CLUSTERS",
    "MOBILITY_AND_FLEET",
    "WORKFORCE_AND_TIME",
    "WORKPLACE_AND_OPERATIONS",
]
