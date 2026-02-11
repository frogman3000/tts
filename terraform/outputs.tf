output "service_url" {
  value       = google_cloud_run_v2_service.default.uri
  description = "The URL of the deployed Cloud Run service"
}

output "bucket_name" {
  value       = google_storage_bucket.app_bucket.name
  description = "The name of the GCS bucket created"
}
