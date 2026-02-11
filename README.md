# TTS Generator
# John O'Donnell - 2026
# Apache 2.0 License


A powerful web application for synthesizing speech using **Google Cloud Text-to-Speech (TTS)** and **Vertex AI Gemini TTS**. This tool allows users to generate high-quality audio from text or documents, manage their generation history, and experiment with different voices and styles.

## Features

- **Multi-Service Support**: 
    - **Google Cloud TTS**: Access standard and premium voices like Chirp, Journey, Neural2, Studio, and WaveNet.
    - **Vertex AI Gemini TTS**: Utilize the latest generative voice models (Puck, Charon, Kore, Fenrir, Aoede, Zephyr).
- **Document Support**: Upload `.txt` or `.pdf` files to synthesize entire documents.
- **History Management**: Automatically saves generation jobs (audio, text, and metadata) to a Google Cloud Storage (GCS) bucket. Users can view, download, and delete past jobs.
- **Branding**: Dynamic theming support (e.g., "Google Cymbal" vs. "Lumeris") for personalized demos.
- **Streaming (Beta)**: Real-time audio streaming capabilities for low-latency feedback.

## Architecture

- **Backend**: Python Flask application.
- **Frontend**: HTML/JS with responsive design.
- **Storage**: Google Cloud Storage (GCS) for persistence.
- **AI Services**: 
    - Google Cloud Text-to-Speech API
    - Vertex AI (Gemini)

## Setup & Installation

### Prerequisites

- Python 3.11+
- Google Cloud Project with the following APIs enabled:
    - Text-to-Speech API
    - Vertex AI API
    - Cloud Storage API

### IAM Roles

Ensure the Service Account used by the application (or your user account for local development) has the following roles:

-   **Storage Admin** (`roles/storage.admin`): Required to create and manage the GCS bucket for history and audio files.
-   **Vertex AI User** (`roles/aiplatform.user`): Required for generating speech with Gemini models.
-   **Cloud Text-to-Speech API User** (or Editor): Required to access standard Google Cloud TTS voices.

### Environment Variables

Create a `.env` file in the root directory with the following variables:

```bash
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_REGION=us-central1
SERVICE_NAME=marketing-tts-generator
REPO_NAME=marketing-tts-repo
```

### Local Development

1.  **Clone the repository**:
    ```bash
    git clone <your-repo-url>
    cd ttsdemo
    ```

2.  **Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the application**:
    ```bash
    python app.py
    ```
    Access the app at `http://localhost:8080`.

## Deployment

The application is containerized and can be deployed to **Google Cloud Run** using the provided script.

1.  Ensure you have the Google Cloud SDK (`gcloud`) installed and authenticated.
2.  Make the deploy script executable:
    ```bash
    chmod +x deploy.sh
    ```
3.  Run the deployment script:
    ```bash
    ./deploy.sh
    ```

### Option 2: Terraform

You can also use Terraform to provision infrastructure and deploy the application.

1.  Navigate to the `terraform` directory:
    ```bash
    cd terraform
    ```

2.  Initialize Terraform:
    ```bash
    terraform init
    ```

3.  Configure variables:
    Rename `terraform.tfvars.example` to `terraform.tfvars` and update the values:
    ```bash
    mv terraform.tfvars.example terraform.tfvars
    # Edit terraform.tfvars with your project_id, etc.
    project_id   = "YOUR_PROJECT_ID"
    region       = "us-central1"
    service_name = "marketing-tts-generator"
    repo_name    = "marketing-tts-repo"
    ```

4.  Apply the configuration:
    ```bash
    terraform apply
    ```

This will automatically:
-   Enable required APIs.
-   Create the GCS bucket and Artifact Registry.
-   Create a Service Account with necessary IAM roles.
-   Build the Docker image (via Cloud Build).
-   Deploy the service to Cloud Run.

### Usage Guide

1.  **Generator Tab**:
    - **Input**: specific a "Job Name", enter text, or upload a file.
    - **Service**: Choose between "Google Cloud TTS" (standard/premium voices) or "Gemini TTS" (generative voices).
    - **Voice**: Filter and select your desired voice.
    - **Controls**: Adjust speed and volume (Chirp only).
    - **Generate**: Click "Generate Speech" to synthesize audio.

2.  **Streaming Tab (Beta)**:
    - Experiment with real-time text-to-speech streaming.

3.  **History Tab**:
    - View a list of all past generation jobs.
    - Play audio directly in the browser.
    - Download audio or source text.
    - Delete unwanted jobs from storage.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE.TXT](LICENSE.TXT) file for details.
