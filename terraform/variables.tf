variable "project_id" {
  description = "The Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "The Google Cloud Region"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "The name of the Cloud Run service"
  type        = string
  default     = "marketing-tts-generator"
}

variable "repo_name" {
  description = "The name of the Artifact Registry repository"
  type        = string
  default     = "marketing-tts-repo"
}
