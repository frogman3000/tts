#!/bin/bash
set -e

# Load environment variables from .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Ensure required variables are set
if [ -z "$GOOGLE_CLOUD_PROJECT" ] || [ -z "$GOOGLE_CLOUD_REGION" ] || [ -z "$SERVICE_NAME" ]; then
  echo "Error: Required environment variables (GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_REGION, SERVICE_NAME) are not set."
  echo "Please check your .env file."
  exit 1
fi

PROJECT_ID="$GOOGLE_CLOUD_PROJECT"
REGION="$GOOGLE_CLOUD_REGION"
# SERVICE_NAME and REPO_NAME are already set from .env
IMAGE_URI="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME"

echo "Deploying $SERVICE_NAME to project $PROJECT_ID in region $REGION..."

# 1. Create Artifact Registry repository if it doesn't exist
if ! gcloud artifacts repositories describe "$REPO_NAME" --project="$PROJECT_ID" --location="$REGION" &>/dev/null; then
  echo "Creating Artifact Registry repository $REPO_NAME..."
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Docker repository for $SERVICE_NAME" \
    --project="$PROJECT_ID"
else
  echo "Artifact Registry repository $REPO_NAME already exists."
fi

# 2. Build and Push the image
echo "Building and pushing image to $IMAGE_URI..."
gcloud builds submit --tag "$IMAGE_URI" . --project="$PROJECT_ID"

# 3. Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE_URI" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --allow-unauthenticated

echo "Deployment complete!"
