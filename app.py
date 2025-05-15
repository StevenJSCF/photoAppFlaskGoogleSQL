from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from google.cloud import storage
import mysql.connector

# Load environment variables from .env file
load_dotenv()

# Flask App Initialization
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Google Cloud Storage Configuration
GCS_BUCKET = os.getenv("GCS_BUCKET")
storage_client = storage.Client()

from google.oauth2 import service_account
credentials = service_account.Credentials.from_service_account_file("key.json")
storage_client = storage.Client(credentials=credentials)

# Google Cloud SQL (MySQL) Configuration
db_config = {
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD", ""),
    'host': os.getenv("DB_HOST"),
    'database': os.getenv("DB_NAME")
}

# Google Cloud SQL (MySQL) Configuration
# db_config = {
#     'user': os.getenv("DB_USER"),
#     'password': os.getenv("DB_PASSWORD", ""),
#     'unix_socket': f"/cloudsql/{os.getenv('DB_CONNECTION_NAME')}", # This tells App Engine to connect using a Unix socket instead of IP which is required in serverless environments
#     'database': os.getenv("DB_NAME")
# }


def get_db_connection():
    return mysql.connector.connect(
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD'),
        host=os.environ.get('DB_HOST'),
        database=os.environ.get('DB_NAME')
    )

# Home Page
@app.route('/')
def home():
    return render_template('index.html')

# User Registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        print(hashed_password)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Users (username, password) VALUES (%s, %s)", (username, hashed_password))
        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('login'))
    return render_template('register.html')

# User Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Users WHERE username=%s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['username'] = username
            flash("Login successful!")
            return redirect(url_for('upload'))
        else:
            flash("Invalid credentials", "error")
    return render_template('login.html')

# Upload Page
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'photo' not in request.files:
            return "No file uploaded"

        file = request.files['photo']
        if file.filename == '':
            return "No file selected"

        filename = secure_filename(file.filename)
        # Upload file to Google Cloud Storage
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(filename)
        blob.upload_from_file(file)

        # Save file info in Google Cloud SQL
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO Photos (username, filename) VALUES (%s, %s)", (session['username'], filename))
        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('gallery'))
    return render_template('upload.html')

# Gallery Page
@app.route('/gallery')
def gallery():
    if 'username' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT filename FROM Photos WHERE username=%s", (session['username'],))
    photos = cursor.fetchall()
    cursor.close()
    conn.close()

    photo_data = []
    for photo in photos:
        filename = photo['filename']
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(filename)
        # Generate signed URLs valid for 1 hour
        view_url = blob.generate_signed_url(version="v4", expiration=3600, method="GET")
        download_url = blob.generate_signed_url(
            version="v4",
            expiration=3600,
            method="GET",
            response_disposition='attachment'
        )
        photo_data.append({
            'view_url': view_url,
            'download_url': download_url,
            'filename': filename
        })

    return render_template('gallery.html', photos=photo_data)

# Search Page
@app.route('/search', methods=['GET', 'POST'])
def search():
    if 'username' not in session:
        return redirect(url_for('login'))

    photo_data = []
    if request.method == 'POST':
        keyword = request.form['keyword']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT filename FROM Photos WHERE username=%s AND filename LIKE %s", (session['username'], '%' + keyword + '%'))
        photos = cursor.fetchall()
        cursor.close()
        conn.close()

        for photo in photos:
            filename = photo['filename']
            bucket = storage_client.bucket(GCS_BUCKET)
            blob = bucket.blob(filename)
            view_url = blob.generate_signed_url(version="v4", expiration=3600, method="GET")
            download_url = blob.generate_signed_url(
                version="v4",
                expiration=3600,
                method="GET",
                response_disposition='attachment'
            )
            photo_data.append({
                'view_url': view_url,
                'download_url': download_url,
                'filename': filename
            })

        return render_template('search_results.html', photos=photo_data)
    return render_template('search.html')

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
