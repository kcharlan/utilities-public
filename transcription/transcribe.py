import streamlit as st
import whisper
import glob
import os
import json

# --- Updated CSS with the confusing upload-section removed ---
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0 2rem 0;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 2.5rem;
        font-weight: 700;
        margin-bottom: 0;
    }
    
    .subtitle {
        text-align: center;
        color: #6b7280;
        font-size: 1.1rem;
        margin-bottom: 2rem;
    }
    
    .section-header {
        color: #374151;
        font-weight: 600;
        font-size: 1.3rem;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #e5e7eb;
    }
    
    /* Counter styles */
    .counter-container {
        background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 4px solid #10b981;
    }
    
    .counter-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin: 0.5rem 0;
    }
    
    .counter-label {
        font-weight: 600;
        color: #374151;
        font-size: 1rem;
    }
    
    .counter-time {
        font-family: 'Monaco', 'Menlo', monospace;
        font-size: 1.2rem;
        font-weight: 700;
        color: #059669;
        background: white;
        padding: 0.3rem 0.8rem;
        border-radius: 6px;
        border: 1px solid #d1d5db;
    }
    
    /* Style the actual file uploader to be more prominent */
    .stFileUploader {
        background: linear-gradient(135deg, #667eea10 0%, #764ba210 100%) !important;
        border-radius: 12px !important;
        padding: 1.5rem !important;
        margin: 1rem 0 !important;
        border: 2px dashed #667eea !important;
        transition: all 0.3s ease;
    }
    
    .stFileUploader:hover {
        border-color: #764ba2 !important;
        background: linear-gradient(135deg, #667eea20 0%, #764ba220 100%) !important;
    }
    
    .stFileUploader > div {
        border: none !important;
        background: transparent !important;
    }
    
    /* Fix for dark mode - ensure text is visible */
    .stSelectbox > div > div {
        background-color: var(--background-color, #f9fafb) !important;
    }
    
    .stSelectbox > div > div > div {
        color: var(--text-color, #1f2937) !important;
    }
    
    .stTextInput > div > div > input {
        background-color: var(--background-color, #f9fafb) !important;
        border-radius: 8px;
        border: 1px solid #d1d5db;
        color: var(--text-color, #1f2937) !important;
    }
    
    .stTextInput > div > div > input::placeholder {
        color: var(--text-color-60, #6b7280) !important;
    }
    
    .stButton > button {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
        border-radius: 8px;
        border: none;
        padding: 0.6rem 2rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    .stTextArea > div > div > textarea {
        background-color: var(--background-color, #f9fafb) !important;
        border-radius: 8px;
        border: 1px solid #d1d5db;
        font-family: 'Monaco', 'Menlo', monospace;
        color: var(--text-color, #1f2937) !important;
    }
    
    .file-card {
        background: var(--secondary-background-color, white);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        border-left: 4px solid #667eea;
    }
    
    .stAlert {
        border-radius: 8px;
    }
    
    /* Dark mode specific overrides */
    @media (prefers-color-scheme: dark) {
        .counter-container {
            background: linear-gradient(135deg, #374151 0%, #4b5563 100%);
            border-left-color: #10b981;
        }
        
        .counter-label {
            color: #f9fafb;
        }
        
        .counter-time {
            background: #1f2937;
            color: #34d399;
            border-color: #6b7280;
        }
        
        .stSelectbox > div > div {
            background-color: #374151 !important;
        }
        
        .stSelectbox > div > div > div {
            color: #f9fafb !important;
        }
        
        .stTextInput > div > div > input {
            background-color: #374151 !important;
            color: #f9fafb !important;
            border-color: #4b5563;
        }
        
        .stTextInput > div > div > input::placeholder {
            color: #9ca3af !important;
        }
        
        .stTextArea > div > div > textarea {
            background-color: #374151 !important;
            color: #f9fafb !important;
            border-color: #4b5563;
        }
        
        .stFileUploader {
            background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%) !important;
            border-color: #667eea !important;
        }
        
        .stFileUploader:hover {
            border-color: #764ba2 !important;
            background: linear-gradient(135deg, #667eea25 0%, #764ba225 100%) !important;
        }
        
        .file-card {
            background: #1f2937;
        }
        
        .section-header {
            color: #f9fafb;
            border-bottom-color: #4b5563;
        }
        
        .subtitle {
            color: #9ca3af;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- Helper Functions ---

def process_text_with_dividers(text, divider_words):
    import re
    if not divider_words:
        return text
    pattern = r'\b(?:' + '|'.join(re.escape(word) for word in divider_words) + r')\b[,\s]*'
    segments = re.split(pattern, text, flags=re.IGNORECASE)
    processed_segments = [segment.strip() for segment in segments if segment.strip()]
    return '\n\n'.join(processed_segments)

def expand_wildcard_paths(pattern):
    return glob.glob(os.path.expanduser(pattern))

def get_file_names_from_uploads(uploaded_files):
    import tempfile
    temp_dir = tempfile.mkdtemp()
    file_paths = []
    for uploaded_file in uploaded_files:
        file_path = os.path.join(temp_dir, uploaded_file.name)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        file_paths.append(file_path)
    return file_paths

def seconds_to_hms(seconds):
    """Convert seconds to HH:MM:SS format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def load_lifetime_odometer():
    """Load the lifetime odometer from file"""
    odometer_file = "transcription_odometer.txt"
    try:
        with open(odometer_file, 'r') as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0.0

def save_lifetime_odometer(total_seconds):
    """Save the lifetime odometer to file"""
    odometer_file = "transcription_odometer.txt"
    with open(odometer_file, 'w') as f:
        f.write(str(total_seconds))

def load_cumulative_counter():
    """Load cumulative counter from session state or initialize"""
    if 'cumulative_total_seconds' not in st.session_state:
        # Try to load from a session backup file
        backup_file = "session_backup.json"
        try:
            with open(backup_file, 'r') as f:
                data = json.load(f)
                st.session_state['cumulative_total_seconds'] = data.get('cumulative_seconds', 0.0)
        except (FileNotFoundError, json.JSONDecodeError):
            st.session_state['cumulative_total_seconds'] = 0.0
    return st.session_state['cumulative_total_seconds']

def save_cumulative_counter():
    """Save cumulative counter to backup file"""
    backup_file = "session_backup.json"
    data = {'cumulative_seconds': st.session_state.get('cumulative_total_seconds', 0.0)}
    with open(backup_file, 'w') as f:
        json.dump(data, f)

def get_audio_duration(file_path):
    """Get duration of audio file using librosa or fallback methods"""
    try:
        # Try using librosa first (most accurate)
        import librosa
        y, sr = librosa.load(file_path, sr=None)
        return len(y) / sr
    except ImportError:
        try:
            # Fallback to using whisper's load_audio
            import whisper
            audio = whisper.load_audio(file_path)
            return len(audio) / whisper.audio.SAMPLE_RATE
        except:
            # Last resort - return 0 if we can't determine duration
            return 0.0

# --- Initialize counters ---
if 'current_session_seconds' not in st.session_state:
    st.session_state['current_session_seconds'] = 0.0

# Load counters on startup
cumulative_seconds = load_cumulative_counter()
lifetime_seconds = load_lifetime_odometer()

# --- Streamlit UI ---

st.set_page_config(
    page_title="Whisper Transcriber", 
    layout="wide",
    page_icon="🎙️"
)

# Header
st.markdown('<h1 class="main-header">🎙️ Whisper Transcriber</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Transform your audio files into text with OpenAI\'s powerful Whisper model</p>', unsafe_allow_html=True)

# Configuration Section
st.markdown('<h3 class="section-header">⚙️ Configuration</h3>', unsafe_allow_html=True)

col1, col2 = st.columns([1, 1])

with col1:
    model_name = st.selectbox(
        label="Select Whisper Model",
        options=["tiny", "base", "small", "medium", "large"],
        index=4,
        help="🔍 Larger models provide better accuracy but take longer to process"
    )

with col2:
    divider_input = st.text_input(
        label="Divider Words (space-separated)",
        value="cut mark",
        help="✂️ Words that will split your transcript into sections. Leave blank to disable."
    )

divider_words = [w for w in divider_input.strip().split() if w] if divider_input.strip() else []

# File Selection Section
st.markdown('<h3 class="section-header">📁 Select Audio Files</h3>', unsafe_allow_html=True)

# Direct file uploader - no confusing wrapper
uploaded_files = st.file_uploader(
    label="Drag & drop audio files here or click to browse",
    type=["wav", "mp3", "m4a", "ogg", "flac", "aac"],
    accept_multiple_files=True,
    help="📎 Supports WAV, MP3, M4A, OGG, FLAC, and AAC files"
)

# Advanced option for file paths (collapsed by default)
show_advanced = st.checkbox("🔧 Use file path/wildcard instead", value=False)

if show_advanced:
    st.markdown("---")
    file_pattern = st.text_input(
        label="File Path or Wildcard Pattern",
        value="",
        placeholder="e.g., /path/to/audio/*.wav or ~/Downloads/*.mp3",
        help="🔍 Use wildcards (*) to select multiple files at once"
    )
else:
    file_pattern = ""

# Process file selection
files_to_process = []
if file_pattern and show_advanced:
    files_to_process = expand_wildcard_paths(file_pattern)
elif uploaded_files:
    files_to_process = get_file_names_from_uploads(uploaded_files)

# File status
if files_to_process:
    st.success(f"🎧 Ready to transcribe {len(files_to_process)} file(s)")
    with st.expander("📋 View selected files"):
        for i, file in enumerate(files_to_process, 1):
            st.write(f"{i}. `{os.path.basename(file)}`")
else:
    st.info("👆 Please select audio files using the drag & drop area above")

# Transcription Section
st.markdown('<h3 class="section-header">🚀 Transcription</h3>', unsafe_allow_html=True)

transcribe_btn = st.button(
    "🎯 Start Transcription", 
    disabled=not files_to_process,
    help="Click to begin transcribing your selected audio files"
)

# --- Transcription Logic ---

if transcribe_btn:
    # Reset current session counter
    st.session_state['current_session_seconds'] = 0.0
    
    st.session_state['transcriptions'] = []
    st.session_state['raw_texts'] = []
    st.session_state['processed_texts'] = []
    st.session_state['file_names'] = files_to_process

    with st.spinner(f"🔄 Loading Whisper model '{model_name}'..."):
        try:
            model = whisper.load_model(model_name)
        except Exception as e:
            st.error(f"❌ Error loading model '{model_name}': {e}")
            st.stop()

    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_duration = 0.0
    
    for idx, file in enumerate(files_to_process):
        status_text.write(f"🎵 Transcribing: **{os.path.basename(file)}** ({idx + 1}/{len(files_to_process)})")
        try:
            # Get audio duration
            duration = get_audio_duration(file)
            total_duration += duration
            
            # Transcribe
            result = model.transcribe(file)
            raw_text = result["text"]
        except Exception as e:
            raw_text = f"[ERROR] Could not transcribe {file}: {e}"
            
        st.session_state['raw_texts'].append(raw_text)
        st.session_state['processed_texts'].append("")
        progress_bar.progress((idx + 1) / len(files_to_process))
    
    # Update all counters
    st.session_state['current_session_seconds'] = total_duration
    st.session_state['cumulative_total_seconds'] = cumulative_seconds + total_duration
    
    # Save counters
    save_cumulative_counter()
    save_lifetime_odometer(lifetime_seconds + total_duration)
    
    progress_bar.empty()
    status_text.empty()
    st.success("✅ Transcription completed successfully!")

# --- Time Counters Display (Always Visible) ---

st.markdown('<h3 class="section-header">⏱️ Transcription Time Counters</h3>', unsafe_allow_html=True)

# Update current values for display
current_seconds = st.session_state.get('current_session_seconds', 0.0)
cumulative_seconds = st.session_state.get('cumulative_total_seconds', 0.0)
lifetime_seconds = load_lifetime_odometer()

st.markdown(f"""
<div class="counter-container">
    <div class="counter-row">
        <span class="counter-label">🎯 Current Session:</span>
        <span class="counter-time">{seconds_to_hms(current_seconds)}</span>
    </div>
    <div class="counter-row">
        <span class="counter-label">📈 Cumulative Total:</span>
        <span class="counter-time">{seconds_to_hms(cumulative_seconds)}</span>
    </div>
    <div class="counter-row">
        <span class="counter-label">🏆 Lifetime Odometer:</span>
        <span class="counter-time">{seconds_to_hms(lifetime_seconds)}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# Reset button for cumulative counter
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("🔄 Reset Cumulative", help="Reset the cumulative counter to 0:00:00"):
        st.session_state['cumulative_total_seconds'] = 0.0
        save_cumulative_counter()
        st.success("Cumulative counter reset!")
        st.rerun()

# --- Results Section ---

if 'raw_texts' in st.session_state and st.session_state['raw_texts']:
    st.markdown('<h3 class="section-header">📄 Transcription Results</h3>', unsafe_allow_html=True)
    
    for idx, file in enumerate(st.session_state['file_names']):
        st.markdown(f'<div class="file-card">', unsafe_allow_html=True)
        
        st.markdown(f"### 📎 {os.path.basename(file)}")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            raw_text = st.text_area(
                label="Raw Transcript",
                value=st.session_state['raw_texts'][idx],
                key=f"raw_{idx}",
                height=200,
                help="✏️ You can edit this transcript before processing"
            )
        
        with col2:
            st.write("")  # Spacing
            st.write("")  # Spacing
            if st.button(
                "✨ Process Text", 
                key=f"process_{idx}",
                help="Apply divider words to split the transcript"
            ):
                processed = process_text_with_dividers(raw_text, divider_words)
                st.session_state['processed_texts'][idx] = processed
                st.success("Text processed!")
        
        if st.session_state['processed_texts'][idx]:
            st.text_area(
                label="Processed Output",
                value=st.session_state['processed_texts'][idx],
                key=f"processed_{idx}",
                height=200,
                help="📝 Final processed transcript with dividers applied"
            )
        
        st.markdown('</div>', unsafe_allow_html=True)

# Footer
st.markdown("---")
st.markdown(
    '<p style="text-align: center; color: #6b7280; font-size: 0.9rem;">Built with ❤️ using Streamlit and OpenAI Whisper</p>', 
    unsafe_allow_html=True
)
