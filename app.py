from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import time
import threading
import ssl

ssl._create_default_https_context = ssl._create_unverified_context

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def get_video_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'no_check_certificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = []
            for f in info.get('formats', []):
                height = f.get('height')
                if height and height >= 360:
                    formats.append({
                        'format_id': f['format_id'],
                        'resolution': f'{height}p',
                        'ext': f['ext'],
                        'filesize': f.get('filesize', 0)
                    })
            
            return {
                'success': True,
                'title': info.get('title', 'Video'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'formats': formats[:5]
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def download_video(url, format_id):
    try:
        timestamp = int(time.time())
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'video_{timestamp}.%(ext)s'),
            'format': format_id,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'ignoreerrors': True,
            'no_check_certificate': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if not os.path.exists(filename):
                base = filename.rsplit('.', 1)[0]
                for ext in ['mp4', 'webm', 'mkv']:
                    if os.path.exists(f'{base}.{ext}'):
                        filename = f'{base}.{ext}'
                        break
            
            return filename, info.get('title', 'video')
    except Exception as e:
        return None, str(e)

def cleanup_old_files():
    while True:
        time.sleep(3600)
        try:
            now = time.time()
            for f in os.listdir(DOWNLOAD_FOLDER):
                path = os.path.join(DOWNLOAD_FOLDER, f)
                if os.path.isfile(path) and now - os.path.getmtime(path) > 3600:
                    os.remove(path)
        except:
            pass

threading.Thread(target=cleanup_old_files, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/api/info', methods=['POST'])
def api_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'URL required'}), 400
    return jsonify(get_video_info(url))

@app.route('/api/download', methods=['POST'])
def api_download():
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('format_id')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL required'}), 400
    
    filepath, title = download_video(url, format_id)
    
    if filepath and os.path.exists(filepath):
        @after_this_request
        def cleanup(response):
            try:
                os.remove(filepath)
            except:
                pass
            return response
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=f"{title}.mp4",
            mimetype='video/mp4'
        )
    else:
        return jsonify({'success': False, 'error': title}), 400

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
