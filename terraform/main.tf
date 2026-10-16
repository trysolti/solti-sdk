# Public PyPI-format Artifact Registry for the Solti Python SDK (`solti-sdk`).
#
# Naming/region conventions follow ../solti/terraform (project solti-487108,
# region us-central1, google provider ~> 7.0).
#
# State: LOCAL terraform.tfstate in this directory (fine for now — the state
# files must never be committed; see .gitignore). Migrate to a remote backend
# (GCS) when this is managed alongside ../solti/terraform.
#
# NOTE: the `google_artifact_registry_repository_iam_member` allUsers grant
# makes packages in this repository publicly downloadable (anonymous
# `pip`/`uv` installs) — that is the intent for an SDK distribution channel.

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

variable "gcp_project_id" {
  type    = string
  default = "solti-487108"
}

variable "gcp_region" {
  type    = string
  default = "us-central1"
}

resource "google_artifact_registry_repository" "solti_pypi" {
  location      = var.gcp_region
  repository_id = "solti-pypi"
  format        = "PYTHON"
  description   = "Public Python package repository for the Solti Platform SDK (solti-sdk)."
}

# Public read access: anonymous download of wheels/sdists.
resource "google_artifact_registry_repository_iam_member" "public_reader" {
  project    = var.gcp_project_id
  location   = google_artifact_registry_repository.solti_pypi.location
  repository = google_artifact_registry_repository.solti_pypi.name
  role       = "roles/artifactregistry.reader"
  member     = "allUsers"
}

output "repository_url" {
  description = "Base URL of the Python repository (for twine upload)."
  value       = "${var.gcp_region}-python.pkg.dev/${var.gcp_project_id}/solti-pypi"
}

output "index_url" {
  description = "Simple-index URL for pip/uv --extra-index-url."
  value       = "${var.gcp_region}-python.pkg.dev/${var.gcp_project_id}/solti-pypi/simple/"
}
