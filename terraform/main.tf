# terraform {
#   backend "gcs" {
#     # The bucket will be passed via command line or config file
#     # bucket = "YOUR_STATE_BUCKET" 
#     prefix = "terraform/state"
#   }
# }

# 1. Enable APIs
resource "google_project_service" "apis" {
  for_each = toset([
    "texttospeech.googleapis.com",
    "aiplatform.googleapis.com",
    "storage.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com"
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# 2. Create GCS Bucket
resource "google_storage_bucket" "app_bucket" {
  name          = "${var.project_id}-marketing-tts"
  location      = var.region
  force_destroy = false 
  uniform_bucket_level_access = true

  cors {
    origin          = ["*"]
    method          = ["GET", "HEAD", "PUT", "POST", "DELETE"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
  
  depends_on = [google_project_service.apis]
}

# 3. Artifact Registry
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = var.repo_name
  description   = "Docker repository for TTS Generator"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# 4. Service Account
resource "google_service_account" "tts_sa" {
  account_id   = "tts-app-sa"
  display_name = "TTS Application Service Account"
}

# 5. IAM Roles
resource "google_project_iam_member" "sa_roles" {
  for_each = toset([
    "roles/storage.admin",
    "roles/aiplatform.user",
    "roles/editor" # Simplified for demo purposes, or specific roles if preferred
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.tts_sa.email}"
}

# 6. Build Image using Cloud Build (via local-exec)
# Terraform cannot natively build docker images without external providers.
# We use a null_resource to trigger the build.
resource "null_resource" "build_image" {
  triggers = {
    # Re-build if any python or html file changes
    # This is a simple approximation
    dir_sha1 = sha1(join("", [for f in fileset("${path.module}/..", "**/*.{py,html,txt,sh,Dockerfile}") : filesha1("${path.module}/../${f}")]))
  }

  provisioner "local-exec" {
    command = <<EOT
      gcloud builds submit --tag ${var.region}-docker.pkg.dev/${var.project_id}/${var.repo_name}/${var.service_name} .. --project ${var.project_id}
    EOT
  }

  depends_on = [google_artifact_registry_repository.repo]
}

# 7. Cloud Run Service
resource "google_cloud_run_v2_service" "default" {
  name     = var.service_name
  location = var.region
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.tts_sa.email
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repo_name}/${var.service_name}"
      
      env {
        name = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name = "GOOGLE_CLOUD_REGION"
        value = var.region
      }
      # Add other env vars if needed
    }
  }

  depends_on = [
    null_resource.build_image,
    google_project_iam_member.sa_roles
  ]
}

# Make it public
# resource "google_cloud_run_service_iam_member" "public_access" {
#   location = google_cloud_run_v2_service.default.location
#   service  = google_cloud_run_v2_service.default.name
#   role     = "roles/run.invoker"
#   member   = "allUsers"
# }
