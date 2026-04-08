from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import time
import threading
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Admin password
ADMIN_PASSWORD = "admin123"

# Store data
verified_users = {}  # ip -> expiry time
daily_downloads = {}  # ip -> {'date': date, 'count': int, 'bonus': int}
share_bonus = {}
email_subscribers = []

# Analytics
analytics = {
    'visitors': defaultdict(int),
    'downloads': defaultdict(int),
    'verified': 0,
    'platforms': defaultdict(int)
}

def get_client_id():
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers.get('X-Forwarded-For').split(',')[0]
    else:
        ip = request.remote_addr
    return ip

def can_download(client_id):
    # Check if user is verified (unlimited for 24 hours)
    if client_id in verified_users:
        expiry = verified_users[client_id]
        if datetime.now() < expiry:
            return True, 'verified', 999
    
    # Free users with bonuses
    today = datetime.now().date()
    if client_id not in daily_downloads:
        daily_downloads[client_id] = {'date': today, 'count': 0, 'bonus': 0}
    
    if daily_downloads[client_id]['date'] != today:
        daily_downloads[client_id] = {'date': today, 'count': 0, 'bonus': 0}
    
    total_allowed = 3 + daily_downloads[client_id]['bonus']
    used = daily_downloads[client_id]['count']
    
    if used >= total_allowed:
        return False, 'limit_reached', total_allowed - used
    
    return True, 'free', total_allowed - used

def increment_download(client_id, platform='unknown'):
    today = datetime.now().date()
    if client_id not in daily_downloads:
        daily_downloads[client_id] = {'date': today, 'count': 0, 'bonus': 0}
    if daily_downloads[client_id]['date'] != today:
        daily_downloads[client_id] = {'date': today, 'count': 0, 'bonus': 0}
    daily_downloads[client_id]['count'] += 1
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    analytics['downloads'][today_str] += 1
    analytics['platforms'][platform] += 1

def add_bonus(client_id, platform):
    today = datetime.now().date()
    if client_id not in daily_downloads:
        daily_downloads[client_id] = {'date': today, 'count': 0, 'bonus': 0}
    if daily_downloads[client_id]['date'] != today:
        daily_downloads[client_id] = {'date': today, 'count': 0, 'bonus': 0}
    
    if 'bonus_platforms' not in daily_downloads[client_id]:
        daily_downloads[client_id]['bonus_platforms'] = []
    
    if platform in daily_downloads[client_id]['bonus_platforms']:
        return False, 'Already claimed'
    
    daily_downloads[client_id]['bonus_platforms'].append(platform)
    daily_downloads[client_id]['bonus'] += 1
    return True, f'+1 download from {platform}!'

def track_visitor():
    today = datetime.now().strftime('%Y-%m-%d')
    analytics['visitors'][today] += 1

def track_verified():
    analytics['verified'] += 1

def get_analytics():
    today = datetime.now().strftime('%Y-%m-%d')
    return {
        'visitors_today': analytics['visitors'][today],
        'visitors_total': sum(analytics['visitors'].values()),
        'downloads_today': analytics['downloads'][today],
        'downloads_total': sum(analytics['downloads'].values()),
        'verified_total': analytics['verified'],
        'top_platforms': dict(analytics['platforms']),
        'subscribers': len(email_subscribers)
    }

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
            
            if info is None:
                return {'success': False, 'error': 'Could not fetch video info'}
            
            formats = []
            if 'formats' in info:
                for f in info['formats']:
                    height = f.get('height')
                    if height and height >= 360:
                        filesize = f.get('filesize', 0)
                        formats.append({
                            'format_id': f['format_id'],
                            'resolution': f'{height}p',
                            'ext': f['ext'],
                            'filesize': filesize,
                            'filesize_mb': round(filesize / 1024 / 1024, 1) if filesize else 0
                        })
            
            platform = 'unknown'
            if 'youtube.com' in url or 'youtu.be' in url:
                platform = 'youtube'
            elif 'tiktok.com' in url:
                platform = 'tiktok'
            elif 'instagram.com' in url:
                platform = 'instagram'
            elif 'facebook.com' in url:
                platform = 'facebook'
            
            return {
                'success': True,
                'title': info.get('title', 'Video'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'formats': formats[:5],
                'platform': platform
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

def download_batch(urls, format_id):
    results = []
    for url in urls:
        filepath, title = download_video(url, format_id)
        if filepath:
            results.append({'url': url, 'success': True, 'filepath': filepath, 'title': title})
        else:
            results.append({'url': url, 'success': False, 'error': title})
    return results

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

# ============ ROUTES ============

@app.route('/')
def index():
    track_visitor()
    return render_template('index.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/admin')
def admin():
    password = request.args.get('password', '')
    if password != ADMIN_PASSWORD:
        return '<form method="get"><h2>Admin</h2><input type="password" name="password"><button type="submit">Login</button></form>'
    stats = get_analytics()
    return render_template('admin.html', stats=stats)

@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    data = request.get_json()
    email = data.get('email')
    client_id = get_client_id()
    
    if email and email not in email_subscribers:
        email_subscribers.append(email)
        # Give +2 bonus for subscribing
        add_bonus(client_id, 'email_subscribe')
        add_bonus(client_id, 'email_subscribe_2')
        return jsonify({'success': True, 'message': 'Subscribed! +2 downloads added.'})
    return jsonify({'success': False, 'message': 'Email already subscribed'})

@app.route('/api/verify', methods=['POST'])
def verify():
    client_id = get_client_id()
    # Set verified for 24 hours
    verified_users[client_id] = datetime.now() + timedelta(hours=24)
    track_verified()
    return jsonify({'success': True, 'message': 'Verified! Unlimited downloads for 24 hours.'})

@app.route('/api/share', methods=['POST'])
def share():
    client_id = get_client_id()
    data = request.get_json()
    platform = data.get('platform', 'unknown')
    success, message = add_bonus(client_id, platform)
    return jsonify({'success': success, 'message': message})

@app.route('/api/status', methods=['GET'])
def get_status():
    client_id = get_client_id()
    
    # Check verified first
    if client_id in verified_users:
        expiry = verified_users[client_id]
        if datetime.now() < expiry:
            remaining = int((expiry - datetime.now()).total_seconds() / 3600)
            return jsonify({
                'verified': True,
                'remaining_hours': remaining,
                'message': f'✅ UNLIMITED for {remaining} more hours',
                'downloads_left': 999
            })
    
    # Free user
    today = datetime.now().date()
    if client_id not in daily_downloads or daily_downloads[client_id]['date'] != today:
        downloads_left = 3
        bonus = 0
    else:
        bonus = daily_downloads[client_id]['bonus']
        used = daily_downloads[client_id]['count']
        downloads_left = max(0, (3 + bonus) - used)
    
    return jsonify({
        'verified': False,
        'downloads_left': downloads_left,
        'bonus_earned': bonus,
        'message': f'{downloads_left} downloads left today'
    })

@app.route('/api/info', methods=['POST'])
def api_info():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'URL required'}), 400
    return jsonify(get_video_info(url))

@app.route('/api/download', methods=['POST'])
def api_download():
    client_id = get_client_id()
    allowed, reason, remaining = can_download(client_id)
    
    if not allowed:
        return jsonify({'success': False, 'error': 'Daily limit reached. Click VERIFY for unlimited!'}), 403
    
    data = request.get_json()
    url = data.get('url')
    format_id = data.get('format_id')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL required'}), 400
    
    platform = 'unknown'
    if 'youtube.com' in url or 'youtu.be' in url:
        platform = 'youtube'
    elif 'tiktok.com' in url:
        platform = 'tiktok'
    elif 'instagram.com' in url:
        platform = 'instagram'
    elif 'facebook.com' in url:
        platform = 'facebook'
    
    filepath, title = download_video(url, format_id)
    
    if filepath and os.path.exists(filepath):
        increment_download(client_id, platform)
        
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

@app.route('/api/download/batch', methods=['POST'])
def api_download_batch():
    client_id = get_client_id()
    allowed, reason, remaining = can_download(client_id)
    
    if not allowed:
        return jsonify({'success': False, 'error': 'Verify first for unlimited batch downloads!'}), 403
    
    data = request.get_json()
    urls = data.get('urls', [])
    format_id = data.get('format_id', 'best')
    
    if not urls:
        return jsonify({'success': False, 'error': 'No URLs provided'}), 400
    
    import zipfile
    timestamp = int(time.time())
    zip_path = os.path.join(DOWNLOAD_FOLDER, f'batch_{timestamp}.zip')
    
    results = download_batch(urls, format_id)
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for result in results:
            if result['success']:
                zipf.write(result['filepath'], f"{result['title']}.mp4")
                os.remove(result['filepath'])
    
    return send_file(zip_path, as_attachment=True, download_name='videos.zip')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
