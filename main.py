import os
import time
import json
import smtplib
from email.message import EmailMessage
from threading import Thread, Lock
from flask import Flask, render_template, request, jsonify, send_from_directory
from datetime import datetime, timedelta
from pathlib import Path
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError

# ==================== Configuration ====================
CONFIG = {
    "email": {
        "enabled": False,  # Disabled by default for testing
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "sender_email": "your_email@gmail.com",
        "sender_password": "your_app_password",
        "receiver_email": "notification_email@gmail.com"
    },
    "web_ui": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 5000,
        "upload_folder": "uploads",
        "debug": False
    },
    "posting": {
        "default_wait_hours": 10,
        "max_file_size_mb": 50
    }
}

# Ensure upload folder exists
os.makedirs(CONFIG['web_ui']['upload_folder'], exist_ok=True)

# ==================== Core Functionality ====================
class InstagramAutoPoster:
    def __init__(self):
        self.cl = None
        self.app = None
        self.schedule_file = "folder_schedule.json"
        self.posted_file = "posted_folders.txt"
        self.log_file = "instagram_poster.log"
        self.running = False
        self.paused = False
        self.next_post_time = None
        self.current_status = "Idle"
        self.schedule_lock = Lock()
        self.posted_lock = Lock()
        
        # Initialize log file if it doesn't exist
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w') as f:
                f.write("")
        
    # ==================== Logging System ====================
    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] [{level}] {message}"
        print(log_message)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_message + "\n")
    
    # ==================== Email Notification ====================
    def send_email(self, subject, body, is_error=False):
        if not CONFIG['email']['enabled']:
            return
            
        try:
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = CONFIG['email']['sender_email']
            msg['To'] = CONFIG['email']['receiver_email']
            msg.set_content(body)
            
            with smtplib.SMTP(CONFIG['email']['smtp_server'], CONFIG['email']['smtp_port']) as server:
                server.starttls()
                server.login(CONFIG['email']['sender_email'], CONFIG['email']['sender_password'])
                server.send_message(msg)
                
            self.log(f"Email notification sent: {subject}")
        except Exception as e:
            self.log(f"Failed to send email: {str(e)}", "ERROR")
    
    # ==================== Instagram Client Setup ====================
    def setup_client(self):
        try:
            self.cl = Client()
            session_file = "instagram_session.json"
            
            if os.path.exists(session_file):
                try:
                    self.cl.load_settings(session_file)
                    # Try to get account info to verify session
                    self.cl.account_info()
                    self.log("Successfully loaded Instagram session")
                    return True
                except (LoginRequired, ClientError) as e:
                    self.log(f"Saved session invalid: {str(e)}", "WARNING")
                    os.remove(session_file)  # Remove invalid session file
            
            # Manual login if no valid session
            username = input("Enter Instagram username: ")
            password = input("Enter Instagram password: ")
            
            try:
                self.cl.login(username, password)
                self.cl.dump_settings(session_file)
                self.log("Successfully logged in to Instagram")
                return True
            except Exception as e:
                self.log(f"Login failed: {str(e)}", "ERROR")
                return False
        except Exception as e:
            self.log(f"Error setting up Instagram client: {str(e)}", "ERROR")
            return False
    
    # ==================== Folder Scheduling ====================
    def load_schedule(self):
        with self.schedule_lock:
            if not os.path.exists(self.schedule_file):
                return {}
                
            try:
                with open(self.schedule_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.log(f"Error loading schedule: {str(e)}", "ERROR")
                return {}
    
    def save_schedule(self, schedule):
        with self.schedule_lock:
            try:
                with open(self.schedule_file, "w") as f:
                    json.dump(schedule, f, indent=2)
            except IOError as e:
                self.log(f"Error saving schedule: {str(e)}", "ERROR")
    
    def get_next_scheduled_folder(self):
        try:
            schedule = self.load_schedule()
            now = datetime.now()
            
            for folder, data in schedule.items():
                if not os.path.exists(folder):
                    self.log(f"Scheduled folder not found: {folder}", "WARNING")
                    continue
                    
                if data.get('paused', False):
                    continue
                    
                try:
                    post_time = datetime.strptime(data['post_time'], "%Y-%m-%d %H:%M:%S")
                    if post_time > now and not self.is_folder_posted(folder):
                        return folder, post_time
                except ValueError as e:
                    self.log(f"Invalid post time format for folder {folder}: {str(e)}", "ERROR")
                    continue
                    
            return None, None
        except Exception as e:
            self.log(f"Error getting next scheduled folder: {str(e)}", "ERROR")
            return None, None
    
    # ==================== Folder Management ====================
    def is_folder_posted(self, folder):
        with self.posted_lock:
            if not os.path.exists(self.posted_file):
                return False
                
            try:
                with open(self.posted_file, "r") as f:
                    posted_folders = [line.strip() for line in f.readlines()]
                    return folder in posted_folders
            except IOError as e:
                self.log(f"Error reading posted folders: {str(e)}", "ERROR")
                return False
    
    def mark_folder_as_posted(self, folder):
        with self.posted_lock:
            try:
                with open(self.posted_file, "a") as f:
                    f.write(f"{folder}\n")
            except IOError as e:
                self.log(f"Error marking folder as posted: {str(e)}", "ERROR")
    
    def skip_folder(self, folder):
        self.mark_folder_as_posted(folder)
        self.log(f"Folder {folder} manually skipped")
    
    def get_media_files(self, folder_path):
        try:
            media_files = []
            valid_ext = ('.jpg', '.jpeg', '.png', '.mp4')
            
            if not os.path.exists(folder_path):
                self.log(f"Folder not found: {folder_path}", "ERROR")
                return []
            
            for file in os.listdir(folder_path):
                file_path = os.path.join(folder_path, file)
                if os.path.isfile(file_path) and file.lower().endswith(valid_ext):
                    media_files.append(file_path)
            
            return sorted(media_files)
        except Exception as e:
            self.log(f"Error getting media files: {str(e)}", "ERROR")
            return []
    
    def get_caption(self, folder_path):
        caption_path = os.path.join(folder_path, "caption.txt")
        if os.path.exists(caption_path):
            try:
                with open(caption_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except IOError as e:
                self.log(f"Error reading caption file: {str(e)}", "ERROR")
        return ""
    
    # ==================== Posting Logic ====================
    def post_media(self, media_path, caption):
        try:
            if not self.cl:
                return False, "Instagram client not initialized"
                
            if not os.path.exists(media_path):
                return False, f"Media file not found: {media_path}"
            
            is_video = media_path.lower().endswith('.mp4')
            
            self.log(f"Attempting to post {'video' if is_video else 'photo'}: {media_path}")
            
            if is_video:
                media = self.cl.clip_upload(media_path, caption=caption)
            else:
                media = self.cl.photo_upload(media_path, caption=caption)
                
            self.log(f"Posted successfully! Media ID: {media.id}")
            return True, f"Posted successfully! Media ID: {media.id}"
        except Exception as e:
            error_msg = str(e)
            self.log(f"Failed to post media: {error_msg}", "ERROR")
            return False, error_msg
    
    def process_folder(self, folder):
        try:
            folder_path = os.path.abspath(folder)
            media_files = self.get_media_files(folder_path)
            caption = self.get_caption(folder_path)
            
            if not media_files:
                self.log(f"No media files in {folder}", "WARNING")
                self.mark_folder_as_posted(folder)
                return False, "No media files found"
            
            self.log(f"Processing folder: {folder} with {len(media_files)} media files")
            
            for media_path in media_files:
                success, message = self.post_media(media_path, caption)
                if not success:
                    return False, message
                # Add delay between posts if multiple media files
                if len(media_files) > 1:
                    time.sleep(10)  # 10 second delay between posts
            
            self.mark_folder_as_posted(folder)
            return True, "All media posted successfully"
        except Exception as e:
            error_msg = str(e)
            self.log(f"Error processing folder {folder}: {error_msg}", "ERROR")
            return False, error_msg
    
    # ==================== Web Dashboard ====================
    def setup_web_ui(self):
        if not CONFIG['web_ui']['enabled']:
            return
            
        try:
            self.app = Flask(__name__)
            self.app.config['UPLOAD_FOLDER'] = CONFIG['web_ui']['upload_folder']
            
            @self.app.route('/')
            def dashboard():
                try:
                    schedule = self.load_schedule()
                    posted_folders = []
                    
                    if os.path.exists(self.posted_file):
                        with open(self.posted_file, "r") as f:
                            posted_folders = [line.strip() for line in f.readlines()]
                    
                    # Get all folders in the current directory (excluding hidden and upload folder)
                    all_folders = [f for f in os.listdir('.') 
                                 if os.path.isdir(f) 
                                 and not f.startswith('.') 
                                 and f != CONFIG['web_ui']['upload_folder']]
                    
                    # Format next post time for display
                    next_post_display = None
                    if self.next_post_time:
                        next_post_display = self.next_post_time.strftime("%Y-%m-%d %H:%M:%S")
                    
                    return render_template('dashboard.html', 
                                         status=self.current_status,
                                         next_post=next_post_display,
                                         schedule=schedule,
                                         posted_folders=posted_folders,
                                         all_folders=sorted(all_folders),
                                         paused=self.paused)
                except Exception as e:
                    self.log(f"Error rendering dashboard: {str(e)}", "ERROR")
                    return "Error loading dashboard", 500
            
            @self.app.route('/api/logs')
            def get_logs():
                try:
                    with open(self.log_file, "r", encoding="utf-8") as f:
                        logs = f.readlines()
                    return jsonify(logs[-100:])  # Return last 100 lines
                except Exception as e:
                    self.log(f"Error getting logs: {str(e)}", "ERROR")
                    return jsonify({"error": str(e)}), 500
            
            @self.app.route('/api/create_folder', methods=['POST'])
            def create_folder():
                try:
                    folder_name = request.form.get('name')
                    if not folder_name:
                        return jsonify({"error": "Folder name required"}), 400
                    
                    # Sanitize folder name
                    folder_name = ''.join(c for c in folder_name if c.isalnum() or c in (' ', '-', '_'))
                    folder_name = folder_name.strip()
                    
                    if not folder_name:
                        return jsonify({"error": "Invalid folder name"}), 400
                        
                    os.makedirs(folder_name, exist_ok=True)
                    return jsonify({"success": True, "folder": folder_name})
                except Exception as e:
                    self.log(f"Error creating folder: {str(e)}", "ERROR")
                    return jsonify({"error": str(e)}), 500
            
            @self.app.route('/api/upload', methods=['POST'])
            def upload_file():
                try:
                    if 'file' not in request.files:
                        return jsonify({"error": "No file uploaded"}), 400
                    
                    file = request.files['file']
                    folder = request.form.get('folder')
                    
                    if not folder or not os.path.exists(folder):
                        return jsonify({"error": "Invalid folder"}), 400
                    
                    if file.filename == '':
                        return jsonify({"error": "No selected file"}), 400
                    
                    # Ensure filename is safe
                    filename = os.path.basename(file.filename)
                    if not filename:
                        return jsonify({"error": "Invalid filename"}), 400
                    
                    file_path = os.path.join(folder, filename)
                    
                    # Check file size
                    max_size = CONFIG['posting']['max_file_size_mb'] * 1024 * 1024
                    if request.content_length > max_size:
                        return jsonify({"error": f"File too large (max {CONFIG['posting']['max_file_size_mb']}MB)"}), 400
                    
                    try:
                        file.save(file_path)
                        return jsonify({"success": True, "path": file_path})
                    except Exception as e:
                        self.log(f"Error saving file: {str(e)}", "ERROR")
                        return jsonify({"error": str(e)}), 500
                except Exception as e:
                    self.log(f"Error handling upload: {str(e)}", "ERROR")
                    return jsonify({"error": "Internal server error"}), 500
            
            @self.app.route('/api/schedule', methods=['GET', 'POST', 'DELETE'])
            def manage_schedule():
                try:
                    if request.method == 'GET':
                        return jsonify(self.load_schedule())
                        
                    elif request.method == 'POST':
                        data = request.get_json()
                        if not data or 'folder' not in data or 'post_time' not in data:
                            return jsonify({"error": "Folder and post_time required"}), 400
                        
                        # Validate folder exists
                        if not os.path.exists(data['folder']):
                            return jsonify({"error": "Folder does not exist"}), 400
                            
                        # Validate post time format
                        try:
                            datetime.strptime(data['post_time'], "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            return jsonify({"error": "Invalid post_time format (use YYYY-MM-DD HH:MM:SS)"}), 400
                            
                        schedule = self.load_schedule()
                        schedule[data['folder']] = {
                            'post_time': data['post_time'],
                            'paused': data.get('paused', False)
                        }
                        self.save_schedule(schedule)
                        return jsonify({"success": True})
                        
                    elif request.method == 'DELETE':
                        folder = request.args.get('folder')
                        if not folder:
                            return jsonify({"error": "Folder name required"}), 400
                            
                        schedule = self.load_schedule()
                        if folder in schedule:
                            del schedule[folder]
                            self.save_schedule(schedule)
                            return jsonify({"success": True})
                        return jsonify({"error": "Folder not found in schedule"}), 404
                except Exception as e:
                    self.log(f"Error managing schedule: {str(e)}", "ERROR")
                    return jsonify({"error": str(e)}), 500
            
            @self.app.route('/api/schedule/pause', methods=['POST'])
            def pause_schedule():
                try:
                    data = request.get_json()
                    folder = data.get('folder')
                    pause = data.get('pause', True)
                    
                    if not folder:
                        return jsonify({"error": "Folder name required"}), 400
                        
                    schedule = self.load_schedule()
                    if folder in schedule:
                        schedule[folder]['paused'] = pause
                        self.save_schedule(schedule)
                        action = "paused" if pause else "resumed"
                        return jsonify({"success": True, "message": f"Folder {folder} {action}"})
                    return jsonify({"error": "Folder not found in schedule"}), 404
                except Exception as e:
                    self.log(f"Error pausing schedule: {str(e)}", "ERROR")
                    return jsonify({"error": str(e)}), 500
            
            @self.app.route('/api/schedule/skip', methods=['POST'])
            def skip_folder():
                try:
                    data = request.get_json()
                    folder = data.get('folder')
                    if not folder:
                        return jsonify({"error": "Folder name required"}), 400
                        
                    self.skip_folder(folder)
                    return jsonify({"success": True, "message": f"Folder {folder} skipped"})
                except Exception as e:
                    self.log(f"Error skipping folder: {str(e)}", "ERROR")
                    return jsonify({"error": str(e)}), 500
            
            @self.app.route('/api/control', methods=['POST'])
            def control_poster():
                try:
                    data = request.get_json()
                    action = data.get('action')
                    
                    if action == 'pause':
                        self.paused = True
                        self.current_status = "Paused"
                        return jsonify({"success": True, "message": "Poster paused"})
                    elif action == 'resume':
                        self.paused = False
                        self.current_status = "Running"
                        return jsonify({"success": True, "message": "Poster resumed"})
                    elif action == 'stop':
                        self.running = False
                        self.current_status = "Stopped"
                        return jsonify({"success": True, "message": "Poster stopping"})
                    else:
                        return jsonify({"error": "Invalid action"}), 400
                except Exception as e:
                    self.log(f"Error controlling poster: {str(e)}", "ERROR")
                    return jsonify({"error": str(e)}), 500
            
            @self.app.route('/uploads/<filename>')
            def uploaded_file(filename):
                try:
                    return send_from_directory(self.app.config['UPLOAD_FOLDER'], filename)
                except Exception as e:
                    self.log(f"Error serving uploaded file: {str(e)}", "ERROR")
                    return "File not found", 404
            
        except Exception as e:
            self.log(f"Error setting up web UI: {str(e)}", "ERROR")
    
    # ==================== Main Loop ====================
    def run(self):
        if not self.setup_client():
            self.log("Failed to initialize Instagram client", "ERROR")
            return
            
        if CONFIG['web_ui']['enabled']:
            self.setup_web_ui()
            Thread(target=lambda: self.app.run(
                host=CONFIG['web_ui']['host'],
                port=CONFIG['web_ui']['port'],
                debug=CONFIG['web_ui']['debug']
            )).start()
        
        self.running = True
        self.current_status = "Running"
        
        while self.running:
            if self.paused:
                time.sleep(1)
                continue
                
            folder, post_time = self.get_next_scheduled_folder()
            
            if folder:
                self.next_post_time = post_time
                self.log(f"Next post scheduled for {post_time} (folder: {folder})")
                
                # Wait until posting time
                while datetime.now() < post_time and self.running and not self.paused:
                    time.sleep(1)
                
                if not self.running or self.paused:
                    continue
                    
                # Process the folder
                self.current_status = f"Posting {folder}"
                success, message = self.process_folder(folder)
                
                # Send notification
                if success:
                    subject = "Instagram Post Success"
                    self.send_email(subject, f"Folder {folder} posted successfully at {datetime.now()}")
                else:
                    subject = "Instagram Post Failed"
                    self.send_email(subject, f"Failed to post folder {folder}\nError: {message}", True)
                
                self.current_status = "Running"
            else:
                self.log("No scheduled folders found. Waiting...")
                time.sleep(60)  # Check every minute for new schedules

if __name__ == "__main__":
    poster = InstagramAutoPoster()
    try:
        poster.run()
    except KeyboardInterrupt:
        poster.running = False
        poster.current_status = "Stopped"
        poster.log("Script stopped by user")
    except Exception as e:
        poster.log(f"Unexpected error: {str(e)}", "ERROR")