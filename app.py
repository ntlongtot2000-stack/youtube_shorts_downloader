import os
import re
import uuid
import yt_dlp
from urllib.parse import quote
from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS

app = Flask(__name__, template_folder='templates')
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def sanitize_filename(name):
    # Remove characters that are invalid in Windows filenames: \ / : * ? " < > |
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    # Replace multiple spaces with a single space
    sanitized = re.sub(r'\s+', " ", sanitized)
    return sanitized if sanitized else "video"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.json
    url = data.get('url') if data else None
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Simple regex validation for youtube URLs (standard and shorts)
    youtube_regex = (
        r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
        r'(watch\?v=|embed/|v/|shorts/|.+)?([^&=%\?]{11})'
    )
    if not re.match(youtube_regex, url):
        return jsonify({'error': 'Vui lòng nhập link YouTube hợp lệ'}), 400
        
    try:
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android']
                }
            }
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Format duration into MM:SS
            duration_secs = info.get('duration', 0)
            if duration_secs:
                minutes = duration_secs // 60
                seconds = duration_secs % 60
                duration_str = f"{minutes:02d}:{seconds:02d}"
            else:
                duration_str = "Unknown"
                
            return jsonify({
                'title': info.get('title'),
                'author': info.get('uploader') or info.get('channel', 'Unknown'),
                'duration': duration_str,
                'thumbnail': info.get('thumbnail') or (info.get('thumbnails')[-1]['url'] if info.get('thumbnails') else None),
                'url': url
            })
    except Exception as e:
        return jsonify({'error': f'Không thể lấy thông tin video: {str(e)}'}), 500

@app.route('/api/prepare', methods=['POST'])
def prepare():
    data = request.json
    url = data.get('url') if data else None
    download_type = data.get('type', 'video') if data else 'video'
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
        
    try:
        # Generate a unique ID for the file to prevent collisions
        file_id = str(uuid.uuid4())
        
        if download_type == 'audio':
            # Audio format: bestaudio in m4a format
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_id}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android']
                    }
                }
            }
        else:
            # Video format: best pre-merged format that has both video and audio in mp4 container
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f'{file_id}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android']
                    }
                }
            }
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')
            
            # Find the actual file generated on disk
            actual_file = None
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(file_id):
                    actual_file = f
                    break
            
            if not actual_file:
                return jsonify({'error': 'Failed to save downloaded file on server'}), 500
                
            return jsonify({
                'success': True,
                'file_id': file_id,
                'filename': actual_file,
                'title': title
            })
            
    except Exception as e:
        return jsonify({'error': f'Lỗi chuẩn bị tải: {str(e)}'}), 500

@app.route('/api/download_file', methods=['GET'])
def download_file():
    file_id = request.args.get('file_id')
    filename = request.args.get('filename')
    title = request.args.get('title', 'video')
    
    if not file_id or not filename:
        return "Missing parameters", 400
        
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return "File not found or already downloaded", 404
        
    # Get extension
    _, ext = os.path.splitext(filename)
    ext = ext.replace('.', '')
    
    mimetype = 'audio/mp4' if ext == 'm4a' else 'video/mp4'
    safe_title = sanitize_filename(title)
    display_filename = f"{safe_title}.{ext}"
    
    # File generator with automatic delete upon completion
    def generate_and_delete(filepath):
        try:
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(65536) # 64KB chunks
                    if not chunk:
                        break
                    yield chunk
        finally:
            # Clean up file on Windows
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"Error removing temp file {filepath}: {e}")
                
    # Use RFC 5987 encoding for safe UTF-8 filenames in header
    encoded_filename = quote(display_filename)
    headers = {
        'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}",
        'Content-Length': str(os.path.getsize(filepath))
    }
    
    return Response(generate_and_delete(filepath), mimetype=mimetype, headers=headers)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

