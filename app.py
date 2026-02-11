import os
import io
import json
from flask import Flask, render_template, request, send_file, jsonify, Response, stream_with_context
from google.cloud import texttospeech
from google.cloud.texttospeech_v1 import StreamingSynthesizeConfig, StreamingSynthesizeRequest, StreamingSynthesisInput, StreamingAudioConfig
import requests
import base64
from google import genai
from google.genai import types
from pypdf import PdfReader
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Initialize Clients
tts_client = texttospeech.TextToSpeechClient()

from google.cloud import storage
storage_client = storage.Client()

# Initialize Gemini Client (Vertex AI)
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")

if not PROJECT_ID:
    print("Warning: GOOGLE_CLOUD_PROJECT not set in environment variables.")

# GCS Bucket Setup
BUCKET_NAME = f"{PROJECT_ID}-marketing-tts"
try:
    bucket = storage_client.bucket(BUCKET_NAME)
    if not bucket.exists():
        print(f"Creating bucket {BUCKET_NAME}...")
        bucket.create(location=LOCATION)
    else:
        print(f"Bucket {BUCKET_NAME} already exists.")
except Exception as e:
    print(f"Error accessing/creating bucket: {e}")

try:
    gemini_client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION
    )
except Exception as e:
    print(f"Failed to initialize Gemini Client: {e}")
    gemini_client = None

def chunk_text(text, limit=4500):
    """Chunks text into smaller parts respecting word boundaries."""
    chunks = []
    current_chunk = ""
    words = text.split()
    
    for word in words:
        if len(current_chunk) + len(word) + 1 > limit:
            chunks.append(current_chunk)
            current_chunk = word
        else:
            if current_chunk:
                current_chunk += " " + word
            else:
                current_chunk = word
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

import wave
import uuid
import datetime

HISTORY_FILE = 'history.json'
OUTPUT_FOLDER = 'output'

# Ensure output directory exists (also done via shell but good for robustness)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def load_history():
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(HISTORY_FILE)
        if blob.exists():
            content = blob.download_as_text()
            return json.loads(content)
        return []
    except Exception as e:
        print(f"Error loading history: {e}")
        return []

def save_history(entry):
    try:
        history = load_history()
        history.insert(0, entry) # Prepend to show newest first
        
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(HISTORY_FILE)
        blob.upload_from_string(json.dumps(history, indent=2), content_type='application/json')
    except Exception as e:
        print(f"Error saving history: {e}")

def pcm_to_wav(pcm_data, sample_rate=24000):
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2) # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    wav_io.seek(0)
    return wav_io

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/LICENSE.TXT')
def serve_license():
    return send_file('LICENSE.TXT')

@app.route('/history', methods=['GET'])
def get_history():
    return jsonify(load_history())

@app.route('/architecture')
def architecture():
    return render_template('architecture.html')

@app.route('/output/<path:filename>')
def serve_output(filename):
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        
        if not blob.exists():
            return "File not found", 404
             
        # Determine content type based on extension
        if filename.endswith('.mp3'):
            content_type = 'audio/mpeg'
        elif filename.endswith('.wav'):
            content_type = 'audio/wav'
        elif filename.endswith('.txt'):
            content_type = 'text/plain'
        else:
            content_type = 'application/octet-stream'
        
        # Create a file-like object from the blob
        file_obj = io.BytesIO()
        blob.download_to_file(file_obj)
        file_obj.seek(0)
        
        return send_file(
            file_obj,
            mimetype=content_type,
            as_attachment=False,
            download_name=filename.split('/')[-1] # Use only basename for download
        )
    except Exception as e:
        print(f"Error serving file: {e}")
        return "Error serving file", 500

@app.route('/extract_text', methods=['POST'])
def extract_text():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    try:
        text = ""
        if file.filename.lower().endswith('.pdf'):
            reader = PdfReader(file)
            for page in reader.pages:
                text_page = page.extract_text()
                if text_page:
                    text += text_page + "\n"
        elif file.filename.lower().endswith('.txt'):
            text = file.read().decode('utf-8')
        else:
             return jsonify({"error": "Unsupported file type"}), 400
             
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/history/<history_id>', methods=['DELETE'])
def delete_history_item(history_id):
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        history = load_history()
        
        # Find item
        item_index = -1
        item = None
        for i, entry in enumerate(history):
            if entry['id'] == history_id:
                item_index = i
                item = entry
                break
        
        if item_index == -1:
             return jsonify({"error": "Item not found"}), 404
             
        # Delete from GCS
        # Strategy: 
        # 1. If 'filename' starts with 'jobs/', delete that directory (prefix)
        # 2. Else delete 'filename' and 'text_url' blobs individually
        
        main_file_path = item.get('filename', '')
        # Handle 'url' or 'text_url' path stripping if needed, but 'filename' should be the key
        
        if main_file_path.startswith('jobs/'):
            # It's a directory structure, delete everything with this prefix
            # path is likely jobs/timestamp_name_id/audio.wav
            # we want jobs/timestamp_name_id/
            parent_dir = os.path.dirname(main_file_path)
            if parent_dir and parent_dir.startswith('jobs/'):
                 blobs = bucket.list_blobs(prefix=parent_dir)
                 for blob in blobs:
                     print(f"Deleting blob: {blob.name}")
                     blob.delete()
        else:
            # Legacy or flat structure
            if main_file_path:
                 blob = bucket.blob(main_file_path)
                 if blob.exists():
                     blob.delete()
            
            # Check for text file (old style might not have it, new style does)
            text_url = item.get('text_url', '')
            if text_url:
                # url is like /output/path/to/file
                # extract path
                if text_url.startswith('/output/'):
                    text_path = text_url[8:]
                    blob = bucket.blob(text_path)
                    if blob.exists():
                        blob.delete()
        
        # Remove from history and save
        del history[item_index]
        
        blob = bucket.blob(HISTORY_FILE)
        blob.upload_from_string(json.dumps(history, indent=2), content_type='application/json')
        
        return jsonify({"message": "Deleted successfully"})

    except Exception as e:
        print(f"Error deleting item: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/voices', methods=['GET'])
def get_voices():
    service = request.args.get('service')
    voices_list = []
    
    if service == 'chirp':
        # List all Google Cloud voices (Chirp, Journey, Neural2, Studio, WaveNet, Standard)
        request_params = texttospeech.ListVoicesRequest(language_code="en-US")
        try:
            response = tts_client.list_voices(request=request_params)
            # Define allowed types
            allowed_types = ["Chirp-HD", "Journey", "Neural2", "Studio", "WaveNet", "Standard", "Wavenet"] 
            
            for voice in response.voices:
                # Check if voice name contains any of the allowed types
                # Also ensure it is en-US
                if "en-US" in voice.language_codes:
                    # Simple check: does the name look like a known type?
                    # Most names are like: en-US-Journey-F, en-US-Neural2-A, en-US-Standard-A
                    # We can just pass them all through if they match en-US, 
                    # but filtering helps avoid "Polyglot" or other odd ones if we don't want them.
                    # Actually, let's just allow everything that is en-US for maximum flexibility, 
                    # or stick to the list to avoid "Polyglot" if that's a thing.
                    # Let's stick to the plan: allow specific high quality ones + standard.
                    
                    is_allowed = False
                    if "Chirp-HD" in voice.name: is_allowed = True
                    elif "Journey" in voice.name: is_allowed = True
                    elif "Neural2" in voice.name: is_allowed = True
                    elif "Studio" in voice.name: is_allowed = True
                    elif "Wavenet" in voice.name: is_allowed = True # 'Wavenet' appears in some older ones? usually 'Standard' is separate type in list?
                    # actually 'Standard' voices usually have 'Standard' in name e.g. en-US-Standard-A
                    elif "Standard" in voice.name: is_allowed = True
                    
                    if is_allowed:
                        voices_list.append({"name": voice.name, "gender": texttospeech.SsmlVoiceGender(voice.ssml_gender).name})
            
            voices_list.sort(key=lambda x: x['name'])
        except Exception as e:
            print(f"Error listing Chirp voices: {e}")
            
    elif service == 'gemini':
        # List standard Gemini TTS options
        voices_list = [
            {"name": "Puck", "gender": "MALE"},
            {"name": "Charon", "gender": "MALE"},
            {"name": "Kore", "gender": "FEMALE"},
            {"name": "Fenrir", "gender": "MALE"},
            {"name": "Aoede", "gender": "FEMALE"},
            {"name": "Zephyr", "gender": "FEMALE"}
        ]
        
    return jsonify(voices_list)

@app.route('/synthesize', methods=['POST'])
def synthesize():
    service = request.form.get('service')
    voice_name = request.form.get('voice')
    prompt = request.form.get('prompt', '')
    
    # Audio Config Params
    try:
        speed = float(request.form.get('speed', 1.0))
        volume = float(request.form.get('volume', 0.0))
    except ValueError:
        speed = 1.0
        volume = 0.0

    text = ""
    original_filename = None

    # Handle Input
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        original_filename = file.filename
        if file.filename.endswith('.pdf'):
            reader = PdfReader(file)
            for page in reader.pages:
                text_page = page.extract_text()
                if text_page:
                    text += text_page + "\n"
        else:
            text = file.read().decode('utf-8')
    elif 'text' in request.form:
        text = request.form['text']
    
    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Chunk the text to avoid service limits
    chunks = chunk_text(text, limit=4000)
    combined_audio = io.BytesIO()
    
    # Generate Timestamp and ID
    # Generate Timestamp and ID
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    
    # Sanitize Job Name
    job_name = request.form.get('job_name', 'Untitled')
    safe_job_name = "".join([c for c in job_name if c.isalnum() or c in (' ', '_', '-')]).rstrip()
    safe_job_name = safe_job_name.replace(' ', '_') or "Untitled"
    
    # Create GCS Directory Path
    job_dir = f"jobs/{timestamp}_{safe_job_name}_{unique_id}"
    
    audio_filename = f"audio.{ 'mp3' if service == 'chirp' else 'wav' }"
    audio_blob_path = f"{job_dir}/{audio_filename}"
    
    text_filename = "source.txt"
    text_blob_path = f"{job_dir}/{text_filename}"

    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        
        # Upload Text immediately
        text_blob = bucket.blob(text_blob_path)
        text_blob.upload_from_string(text, content_type='text/plain')

        if service == 'chirp':
            for i, chunk in enumerate(chunks):
                input_text = texttospeech.SynthesisInput(text=chunk)
                voice_params = texttospeech.VoiceSelectionParams(
                    language_code="en-US",
                    name=voice_name
                )
                audio_config = texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3,
                    speaking_rate=speed,
                    volume_gain_db=volume
                )

                response = tts_client.synthesize_speech(
                    request={"input": input_text, "voice": voice_params, "audio_config": audio_config}
                )
                combined_audio.write(response.audio_content)
                
            combined_audio.seek(0)
            # Upload to GCS
            # Upload to GCS
            blob = bucket.blob(audio_blob_path)
            blob.upload_from_file(combined_audio, content_type='audio/mpeg')

        elif service == 'gemini':
            if not gemini_client:
                 return jsonify({"error": "Gemini Client not initialized"}), 500
            
            instruction = ""
            if prompt:
                instruction = f"Style/Tone Instruction: {prompt}. "

            # Correctly configure the speech generation
            # According to search results, we need 'speech_config' inside 'GenerateContentConfig'
            # or 'voice_config' structure.
            # Since 'response_mime_type' was invalid, we focus on 'speech_config'.
            
            # Construct the config
            # We need to map our voice name to the structure 'prebuilt_voice_config': {'voice_name': ...}
            
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name 
                    )
                )
            )

            # Try again with 'response_mime_type' but ensure it's correct context.
            # Some docs say 'response_mime_type' works in 'generation_config' (which is 'config' here).
            # If 'audio/mp3' failed, maybe 'audio/wav' or just don't specify and assume default?
            # But user said "unsupported response mime type 'audio/mp3' for a multi-modal generation request".
            # This implies the model doesn't support forcing MP3 via that field for MM generation?
            # OR the model expects 'output_modality' to be AUDIO?
            
            # Let's try to just ASK for audio in the prompt and handle whatever bytes come back.
            # And print the mime type of the part if available.
            
            for i, chunk in enumerate(chunks):
                try:
                    response = gemini_client.models.generate_content(
                        model='gemini-2.5-flash-tts',
                        contents=f"{instruction}Read this text: {chunk}",
                        config=types.GenerateContentConfig(
                            speech_config=speech_config,
                            response_mime_type='audio/wav' 
                        )
                    )
                except Exception as e:
                    print(f"Retrying chunk {i} without mime_type due to: {e}")
                    response = gemini_client.models.generate_content(
                        model='gemini-2.5-flash-tts',
                        contents=f"{instruction}Read this text: {chunk}",
                        config=types.GenerateContentConfig(
                            speech_config=speech_config
                        )
                    )

                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data:
                            print(f"Chunk {i} received audio bytes: {len(part.inline_data.data)} bytes, mime_type: {part.inline_data.mime_type}")
                            combined_audio.write(part.inline_data.data)
                        elif part.text:
                            print(f"Warning: Received text instead of audio for chunk {i}: {part.text}")
                else:
                    print(f"Chunk {i} response empty or invalid: {response}")
            
            combined_audio.seek(0)
            if combined_audio.getbuffer().nbytes == 0:
                 return jsonify({"error": "No audio content returned from Gemini"}), 500

            # Wrap PCM in WAV
            wav_audio = pcm_to_wav(combined_audio.read())
            
            # Upload to GCS
            # Upload to GCS
            blob = bucket.blob(audio_blob_path)
            blob.upload_from_file(wav_audio, content_type='audio/wav')
        
        else:
            return jsonify({"error": "Invalid service"}), 400

        # Save History
        # Save History
        history_entry = {
            "id": unique_id,
            "filename": audio_blob_path,
            "url": f"/output/{audio_blob_path}",
            "service": service,
            "voice": voice_name,
            "prompt": prompt,
            "timestamp": timestamp,
            "job_name": job_name,
            "text_url": f"/output/{text_blob_path}",
            "text_snippet": text[:100] + "..." if len(text) > 100 else text
        }
        save_history(history_entry)

        return jsonify({
            "message": "Audio generated successfully",
            "url": f"/output/{audio_blob_path}",
            "text_url": f"/output/{text_blob_path}",
            "entry": history_entry
        })

    except Exception as e:
        print(f"Synthesis Error: {e}")
        return jsonify({"error": str(e)}), 500


def get_wav_header(sample_rate=24000, channels=1):
    import struct
    # RIFF header
    # Use a large file size for streaming
    total_size = 0x7fffffff 
    
    header = b'RIFF'
    header += struct.pack('<I', 36 + total_size)
    header += b'WAVE'
    header += b'fmt '
    header += struct.pack('<I', 16) # Size of fmt chunk
    header += struct.pack('<H', 1)  # Format = 1 (PCM)
    header += struct.pack('<H', channels)
    header += struct.pack('<I', sample_rate)
    header += struct.pack('<I', sample_rate * channels * 2) # ByteRate
    header += struct.pack('<H', channels * 2) # BlockAlign
    header += struct.pack('<H', 16) # BitsPerSample
    header += b'data'
    header += struct.pack('<I', total_size)
    return header

@app.route('/stream')
def stream():
    text = request.args.get('text', '')
    voice_name = request.args.get('voice', 'en-US-Chirp-HD-F')
    
    # Audio Config Params
    try:
        speed = float(request.args.get('speed', 1.0))
        volume = float(request.args.get('volume', 0.0))
    except ValueError:
        speed = 1.0
        volume = 0.0

    if not text:
        return "No text provided", 400

    def generate():
        # 1. Config Request
        streaming_config = StreamingSynthesizeConfig(
            voice=texttospeech.VoiceSelectionParams(
                name=voice_name,
                language_code="en-US"
            )
        )
        yield StreamingSynthesizeRequest(streaming_config=streaming_config)

        # 2. Text Requests
        chunks = chunk_text(text, limit=4000) 
        for chunk in chunks:
            yield StreamingSynthesizeRequest(
                input=StreamingSynthesisInput(text=chunk)
            )

    def stream_speech():
        # Generator for the Flask response
        try:
            # Yield WAV Header first
            yield get_wav_header()
            
            responses = tts_client.streaming_synthesize(generate())
            
            for response in responses:
                if response.audio_content:
                    yield response.audio_content
        except Exception as e:
            print(f"Streaming Error: {e}")
            yield b"" # End stream?

    return Response(stream_with_context(stream_speech()), mimetype="audio/wav")





if __name__ == '__main__':
    app.run(debug=True, port=8080)
