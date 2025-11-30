import os
import uuid
import io
import zipfile
import threading
from datetime import datetime
from flask import (
    Flask, render_template, request, send_file, jsonify
)
from werkzeug.utils import secure_filename
import requests

app = Flask(__name__)
app.secret_key = "your-secret-key"

# ------------------------------------
# FULL GOOGLE TRANSLATE LANGUAGE LIST
# ------------------------------------
LANGUAGE_CODES = {
    "Afrikaans": "af", "Albanian": "sq", "Amharic": "am", "Arabic": "ar",
    "Armenian": "hy", "Assamese": "as", "Aymara": "ay", "Azerbaijani": "az",
    "Basque": "eu", "Belarusian": "be", "Bengali": "bn", "Bosnian": "bs",
    "Bulgarian": "bg", "Catalan": "ca", "Cebuano": "ceb", "Chinese (Simplified)": "zh-CN",
    "Chinese (Traditional)": "zh-TW", "Corsican": "co", "Croatian": "hr", "Czech": "cs",
    "Danish": "da", "Dutch": "nl", "English": "en", "Esperanto": "eo",
    "Estonian": "et", "Filipino": "tl", "Finnish": "fi", "French": "fr",
    "Galician": "gl", "Georgian": "ka", "German": "de", "Greek": "el",
    "Gujarati": "gu", "Haitian Creole": "ht", "Hausa": "ha", "Hebrew": "he",
    "Hindi": "hi", "Hungarian": "hu", "Icelandic": "is", "Igbo": "ig",
    "Indonesian": "id", "Irish": "ga", "Italian": "it", "Japanese": "ja",
    "Javanese": "jv", "Kannada": "kn", "Kazakh": "kk", "Khmer": "km",
    "Kinyarwanda": "rw", "Korean": "ko", "Kurdish": "ku", "Kyrgyz": "ky",
    "Lao": "lo", "Latin": "la", "Latvian": "lv", "Lithuanian": "lt",
    "Luxembourgish": "lb", "Macedonian": "mk", "Malagasy": "mg", "Malay": "ms",
    "Malayalam": "ml", "Maltese": "mt", "Maori": "mi", "Marathi": "mr",
    "Mongolian": "mn", "Nepali": "ne", "Norwegian": "no", "Odia": "or",
    "Pashto": "ps", "Persian": "fa", "Polish": "pl", "Portuguese": "pt",
    "Punjabi": "pa", "Quechua": "qu", "Romanian": "ro", "Russian": "ru",
    "Samoan": "sm", "Sanskrit": "sa", "Scots Gaelic": "gd", "Serbian": "sr",
    "Sesotho": "st", "Shona": "sn", "Sindhi": "sd", "Sinhala": "si",
    "Slovak": "sk", "Slovenian": "sl", "Somali": "so", "Spanish": "es",
    "Sundanese": "su", "Swahili": "sw", "Swedish": "sv", "Tajik": "tg",
    "Tamil": "ta", "Tatar": "tt", "Telugu": "te", "Thai": "th",
    "Turkish": "tr", "Ukrainian": "uk", "Urdu": "ur", "Uyghur": "ug",
    "Uzbek": "uz", "Vietnamese": "vi", "Welsh": "cy", "Xhosa": "xh",
    "Yiddish": "yi", "Yoruba": "yo", "Zulu": "zu"
}

LANGUAGES = sorted(LANGUAGE_CODES.keys())
MAX_CHARS_PER_CHUNK = 5000

JOBS = {}

# ---------------------------
# SPLIT LARGE TEXT
# ---------------------------
def chunk_text(text):
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) < MAX_CHARS_PER_CHUNK:
            current += line + "\n"
        else:
            chunks.append(current)
            current = line + "\n"
    if current.strip():
        chunks.append(current)
    return chunks

# ---------------------------
# GOOGLE TRANSLATE FREE API
# ---------------------------
def google_translate(text, target):

    url = "https://translate.googleapis.com/translate_a/single"

    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target,
        "dt": "t",
        "q": text
    }
    try:
        response = requests.get(url, params=params).json()
        return "".join([sentence[0] for sentence in response[0]])
    except:
        return "[ERROR TRANSLATING CHUNK]"

# ---------------------------
# TRANSLATE FULL TEXT
# ---------------------------
def translate_big(text, lang, job, total_tasks, done_tasks):

    target_code = LANGUAGE_CODES[lang]
    chunks = chunk_text(text)
    output = []

    for i, chunk in enumerate(chunks, start=1):
        output.append(google_translate(chunk, target_code))

        job["sub_progress"] = int(i / len(chunks) * 100)
        base_progress = int(done_tasks / total_tasks * 100)
        job["progress"] = min(base_progress + int((i / len(chunks)) * (1 / total_tasks) * 100), 99)

    return "\n".join(output)

# ---------------------------
# BACKGROUND JOB
# ---------------------------
def run_job(job_id):

    job = JOBS[job_id]
    job["status"] = "running"
    job["progress"] = 0

    files = job["files"]
    text_input = job["text"]
    langs = job["languages"]

    total_tasks = len(files) * len(langs)
    if text_input:
        total_tasks += len(langs)

    done = 0
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zipf:

        # files
        for f in files:
            name = f["name"]
            text = f["text"]

            for lang in langs:
                job["message"] = f"Translating '{name}' → {lang}"
                translated = translate_big(text, lang, job, total_tasks, done)
                zipf.writestr(f"{name}_{lang}.txt", translated)

                done += 1
                job["progress"] = int(done / total_tasks * 100)

        # pasted text
        if text_input:
            pseudo = f"text_{uuid.uuid4().hex[:5]}"
            for lang in langs:
                job["message"] = f"Translating pasted text → {lang}"
                translated = translate_big(text_input, lang, job, total_tasks, done)
                zipf.writestr(f"{pseudo}_{lang}.txt", translated)

                done += 1
                job["progress"] = int(done / total_tasks * 100)

    job["zip"] = zip_buffer.getvalue()
    job["status"] = "done"
    job["progress"] = 100
    job["message"] = "Completed!"

# ---------------------------
# ROUTES
# ---------------------------
@app.route("/")
def home():
    return render_template("base.html")

@app.route("/translator")
def translator():
    return render_template("translator.html", languages=LANGUAGES)

@app.route("/start-translation", methods=["POST"])
def start_translation():

    langs = request.form.getlist("languages")
    files = request.files.getlist("files")
    text = request.form.get("text_input", "").strip()

    if not langs:
        return jsonify({"status": "error", "message": "Select at least one language"})

    if (not files or files[0].filename == "") and not text:
        return jsonify({"status": "error", "message": "Upload files or paste text"})

    file_data = []
    for f in files:
        if f.filename == "":
            continue
        name = secure_filename(f.filename)
        base = os.path.splitext(name)[0]
        content = f.read().decode("utf-8", errors="ignore")
        file_data.append({"name": base, "text": content})

    job_id = uuid.uuid4().hex[:10]

    JOBS[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Starting...",
        "sub_progress": 0,
        "files": file_data,
        "text": text,
        "languages": langs,
        "zip": None
    }

    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()

    return jsonify({"status": "ok", "job_id": job_id})

@app.route("/progress/<job_id>")
def progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"status": "error"})

    safe_job = dict(job)
    safe_job["zip"] = None
    return jsonify(safe_job)

@app.route("/download/<job_id>")
def download(job_id):
    job = JOBS.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"status": "error"}), 400

    buf = io.BytesIO(job["zip"])
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"translations_{job_id}.zip",
        mimetype="application/zip"
    )

if __name__ == "__main__":
    app.run(debug=True)
