# 🤖 Instagram Auto Poster with Web UI

Automatically schedule and post images or videos to Instagram with a powerful web dashboard and email notification support.

> ⚠️ For **educational purposes only**. Do not use on unauthorized accounts.

---

## 📦 Features

- ✅ **Instagram Posting**
  - Automatically posts **images** and **videos** from folders.
  - Posts can be scheduled by **date and time**.
  - **Multiple media files** per folder supported.
  
- 🌐 **Web Dashboard**
  - Upload media to folders via browser.
  - Create folders, view logs, and control posting from UI.
  - Pause/resume/skip scheduled posts.
  
- ✉️ **Email Notifications**
  - Sends success/failure notifications (optional).
  
- 💾 **Session Management**
  - Instagram login saved securely (`instagram_session.json`).
  - Auto login from previous session.

---

## 🗂️ Folder Structure

```
instagram-auto-poster/
│
├── main.py # Main script
├── folder_schedule.json # Stores post schedules
├── posted_folders.txt # Tracks posted folders
├── instagram_session.json # Created after login
├── templates/
│ └── dashboard.html # Web dashboard HTML
├── uploads/ # File upload directory
│
├── 1/
│ ├── image1.jpg
│ ├── video1.mp4
│ └── caption.txt # (optional) Caption text
│
├── 2/
│ ├── another_image.png
│ └── caption.txt
│
├── 3/
│ └── clip.mp4


```


---

## 🚀 How to Run

### 1. 📥 Install Requirements

```bash
pip install instagrapi flask


###2. Run
python main.py



