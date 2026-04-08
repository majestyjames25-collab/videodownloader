from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import time
import threading

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

SUPPORTED_SITES = ['YouTube', 'Instagram', 'TikTok', 'Twitter/X', 'Facebook', 'Reddit', 'Twitch', 'Vimeo']

def get_video_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                    formats.append({
                        'format_id': f['format_id'],
                        'resolution': f.get('height', 'Auto'),
                        'filesize': f.get('filesize', 0),
                        'ext': f['ext']
                    })
            return {
                'success': True,
                'title': info.get('title', 'Untitled'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'views': info.get('view_count', 0),
                'formats': formats[:10],
                'website': info.get('extractor_key', 'Unknown')
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def download_video(url, format_id='best'):
    try:
        timestamp = int(time.time())
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'video_{timestamp}.%(ext)s'),
            'format': format_id,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not os.path.exists(filename):
                filename = filename.rsplit('.', 1)[0] + '.' + info.get('ext', 'mp4')
            return filename, info.get('title', 'video')
    except Exception as e:
        return None, str(e)

def download_audio(url):
    try:
        timestamp = int(time.time())
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'audio_{timestamp}.%(ext)s'),
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = os.path.join(DOWNLOAD_FOLDER, f'audio_{timestamp}.mp3')
            return filename, f"{info.get('title', 'audio')}.mp3"
    except Exception as e:
        return None, str(e)

def cleanup_old_files():
    while True:
        time.sleep(3600)
        try:
            now = time.time()
            for filename in os.listdir(DOWNLOAD_FOLDER):
                filepath = os.path.join(DOWNLOAD_FOLDER, filename)
                if os.path.isfile(filepath) and now - os.path.getmtime(filepath) > 3600:
                    os.remove(filepath)
        except:
            pass

cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()

@app.route('/')
def index():
    return render_template('index.html', sites=SUPPORTED_SITES)

@app.route('/api/info', methods=['POST'])
def api_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'URL required'}), 400
    result = get_video_info(url)
    return jsonify(result)

@app.route('/api/download', methods=['POST'])
def api_download():
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('format_id', 'best')
    download_type = data.get('type', 'video')
    if not url:
        return jsonify({'success': False, 'error': 'URL required'}), 400
    if download_type == 'audio':
        filepath, title = download_audio(url)
    else:
        filepath, title = download_video(url, format_id)
    if filepath and os.path.exists(filepath):
        @after_this_request
        def cleanup(response):
            try:
                os.remove(filepath)
            except:
                pass
            return response
        mimetype = 'audio/mpeg' if download_type == 'audio' else 'video/mp4'
        return send_file(filepath, as_attachment=True, download_name=title, mimetype=mimetype)
    else:
        return jsonify({'success': False, 'error': title}), 400

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
