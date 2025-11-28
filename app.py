import os
import uuid
import io
import zipfile
import threading
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    send_file,
    redirect,
    url_for,
    flash,
    jsonify,
)
from deep_translator import GoogleTranslator
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "your-secret-key"

MAX_CHARS_PER_CHUNK = 5000

LANGUAGE_CODES = {
    "Afrikaans": "af", "Albanian": "sq", "Amharic": "am", "Arabic": "ar", "Armenian": "hy",
    "Assamese": "as", "Aymara": "ay", "Azerbaijani": "az", "Basque": "eu", "Belarusian": "be",
    "Bengali": "bn", "Bosnian": "bs", "Bulgarian": "bg", "Burmese": "my", "Catalan": "ca",
    "Cebuano": "ceb", "Chinese (Simplified)": "zh-CN", "Chinese (Traditional)": "zh-TW",
    "Corsican": "co", "Croatian": "hr", "Czech": "cs", "Danish": "da", "Dutch": "nl",
    "English": "en", "Esperanto": "eo", "Estonian": "et", "Filipino": "tl", "Finnish": "fi",
    "French": "fr", "Frisian": "fy", "Galician": "gl", "Georgian": "ka", "German": "de",
    "Greek": "el", "Gujarati": "gu", "Haitian Creole": "ht", "Hausa": "ha", "Hawaiian": "haw",
    "Hebrew": "he", "Hindi": "hi", "Hmong": "hmn", "Hungarian": "hu", "Icelandic": "is",
    "Igbo": "ig", "Indonesian": "id", "Irish": "ga", "Italian": "it", "Japanese": "ja",
    "Javanese": "jv", "Kannada": "kn", "Kazakh": "kk", "Khmer": "km", "Kinyarwanda": "rw",
    "Korean": "ko", "Kurdish (Kurmanji)": "ku", "Kurdish (Sorani)": "ckb", "Kyrgyz": "ky",
    "Lao": "lo", "Latin": "la", "Latvian": "lv", "Lingala": "ln", "Lithuanian": "lt",
    "Luxembourgish": "lb", "Macedonian": "mk", "Malagasy": "mg", "Malay": "ms", "Malayalam": "ml",
    "Maltese": "mt", "Maori": "mi", "Marathi": "mr", "Mongolian": "mn", "Nepali": "ne",
    "Norwegian": "no", "Odia (Oriya)": "or", "Pashto": "ps", "Persian (Farsi)": "fa",
    "Polish": "pl", "Portuguese": "pt", "Punjabi": "pa", "Quechua": "qu", "Romanian": "ro",
    "Russian": "ru", "Samoan": "sm", "Sanskrit": "sa", "Scots Gaelic": "gd", "Serbian": "sr",
    "Sesotho": "st", "Shona": "sn", "Sindhi": "sd", "Sinhala": "si", "Slovak": "sk",
    "Slovenian": "sl", "Somali": "so", "Spanish": "es", "Sundanese": "su", "Swahili": "sw",
    "Swedish": "sv", "Tajik": "tg", "Tamil": "ta", "Tatar": "tt", "Telugu": "te",
    "Thai": "th", "Tigrinya": "ti", "Turkish": "tr", "Turkmen": "tk", "Ukrainian": "uk",
    "Urdu": "ur", "Uyghur": "ug", "Uzbek": "uz", "Vietnamese": "vi", "Welsh": "cy",
    "Xhosa": "xh", "Yiddish": "yi", "Yoruba": "yo", "Zulu": "zu",
}

# Memory job store
JOBS = {}


def chunk_text(text, max_len=MAX_CHARS_PER_CHUNK):
    chunks, current, length = [], [], 0
    for paragraph in text.split("\n"):
        if length + len(paragraph) + 1 <= max_len:
            current.append(paragraph)
            length += len(paragraph) + 1
        else:
            if current:
                chunks.append("\n".join(current))
            if len(paragraph) > max_len:
                for i in range(0, len(paragraph), max_len):
                    chunks.append(paragraph[i:i + max_len])
                current, length = [], 0
            else:
                current, length = [paragraph], len(paragraph) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


# -------- PREMIUM FIX: Chunk-Level Smooth Progress -------- #
def translate_big_text(text, lang_name, job, total_tasks, done_tasks):
    lang_code = LANGUAGE_CODES[lang_name]
    translator = GoogleTranslator(source="en", target=lang_code)

    chunks = chunk_text(text)
    translated_chunks = []
    total_chunks = len(chunks)

    if total_chunks == 0:
        return ""

    for idx, chunk in enumerate(chunks, start=1):
        # Smooth chunk progress (per chunk)
        sub_progress = int((idx / total_chunks) * 100)
        job["sub_progress"] = sub_progress

        translated = translator.translate(chunk)
        translated_chunks.append(translated)

        # Combine task progress + chunk progress
        base_task_progress = int((done_tasks / total_tasks) * 100)
        blended = base_task_progress + int(sub_progress / total_tasks)

        if blended > 99:
            blended = 99

        job["progress"] = blended

    job["sub_progress"] = 100
    return "\n".join(translated_chunks)


# -------- Background Translation Thread -------- #
def run_translation_job(job_id):
    job = JOBS[job_id]
    job["status"] = "running"
    job["start_time"] = datetime.utcnow()
    job["progress"] = 0
    job["message"] = "Starting..."

    files_data = job["files"]
    text_input = job["text"]
    langs = job["languages"]

    total_tasks = (len(files_data) * len(langs)) + (len(langs) if text_input else 0)
    done_tasks = 0

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:

        # Files
        for f in files_data:
            base_name = f["name"]
            text = f["text"]

            for lang in langs:
                job["message"] = f"Translating '{base_name}' → {lang}..."

                translated = translate_big_text(text, lang, job, total_tasks, done_tasks)

                safe_lang = lang.replace(" ", "_")
                outname = f"{base_name}_{safe_lang}.txt"
                zipf.writestr(outname, translated)

                done_tasks += 1
                job["progress"] = int(done_tasks / total_tasks * 100)

        # Pasted Text
        if text_input:
            pseudo = f"pasted_{uuid.uuid4().hex[:4]}"

            for lang in langs:
                job["message"] = f"Translating pasted text → {lang}..."

                translated = translate_big_text(text_input, lang, job, total_tasks, done_tasks)

                safe_lang = lang.replace(" ", "_")
                outname = f"{pseudo}_{safe_lang}.txt"
                zipf.writestr(outname, translated)

                done_tasks += 1
                job["progress"] = int(done_tasks / total_tasks * 100)

    job["zip"] = zip_buffer.getvalue()
    job["status"] = "done"
    job["progress"] = 100
    job["message"] = "Completed!"


@app.route("/")
def home():
    return render_template("base.html")


@app.route("/translator")
def translator():
    return render_template("translator.html", languages=sorted(LANGUAGE_CODES.keys()))


@app.route("/start-translation", methods=["POST"])
def start_translation():
    langs = request.form.getlist("languages")
    if not langs:
        return jsonify({"status": "error", "message": "Select at least one language"})

    files = request.files.getlist("files")
    text_input = request.form.get("text_input", "").strip()

    if (not files or files[0].filename == "") and not text_input:
        return jsonify({"status": "error", "message": "Upload files or paste text"})

    files_data = []
    if files and files[0].filename != "":
        for file in files:
            if file.filename == "":
                continue
            name = secure_filename(file.filename)
            base, _ = os.path.splitext(name)
            try:
                content = file.read().decode("utf-8", errors="ignore")
            except:
                continue
            if content.strip():
                files_data.append({"name": base, "text": content})

    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Queued",
        "files": files_data,
        "text": text_input,
        "languages": langs,
        "zip": None,
        "start_time": None,
        "sub_progress": 0,
    }

    t = threading.Thread(target=run_translation_job, args=(job_id,), daemon=True)
    t.start()

    return jsonify({"status": "ok", "job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Invalid job"})

    progress = job.get("progress", 0)
    message = job.get("message", "")
    status = job.get("status", "")
    start = job.get("start_time")

    eta = ""
    if start and 0 < progress < 100:
        elapsed = (datetime.utcnow() - start).total_seconds()
        if progress > 0:
            total_est = elapsed / (progress / 100)
            remain = int(total_est - elapsed)
            if remain < 60:
                eta = f"~{remain}s"
            else:
                eta = f"~{remain//60}m {remain%60}s"

    return jsonify({
        "status": status,
        "progress": progress,
        "message": message,
        "eta": eta
    })


@app.route("/download/<job_id>")
def download(job_id):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        flash("Not ready yet")
        return redirect(url_for("translator"))

    buf = io.BytesIO(job["zip"])
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"translations_{job_id}.zip",
        mimetype="application/zip"
    )


if __name__ == "__main__":
    app.run(debug=True, threaded=True)
