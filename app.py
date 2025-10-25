import os, io, uuid
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, send_file, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import LETTER

# --- Flask setup ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///cybercore.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_DIR"] = os.getenv("UPLOAD_DIR", "uploads")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-me-admin-key")

os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

db = SQLAlchemy(app)

# --- DB models ---
class Vendor(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    legal_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    category = db.Column(db.String(100))
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    vendor_type = db.Column(db.String(50))   # local / sub / prime
    kybkyc = db.Column(db.Boolean, default=False)
    paid = db.Column(db.Boolean, default=False)
    score = db.Column(db.Integer, default=0)
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Document(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vendor_id = db.Column(db.String(36), nullable=False)
    kind = db.Column(db.String(50), nullable=False)  # insurance, license, w9, policy
    path = db.Column(db.String(500), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# --- Helpers ---
REQUIRED_DOCS = {"insurance", "license", "w9", "policy"}

def compute_score(vendor_id):
    docs = Document.query.filter_by(vendor_id=vendor_id).all()
    kinds = {d.kind for d in docs}
    return int(100 * len(REQUIRED_DOCS & kinds) / len(REQUIRED_DOCS))

def calc_price(v):
    # $1,500 if they are sub/prime AND selected KYB/KYC
    if v.vendor_type in ("sub", "prime") and v.kybkyc:
        return 1500
    return 1000

def tier_label(v):
    if v.vendor_type in ("sub", "prime") and v.kybkyc:
        return "Prime-Ready (KYC/KYB)"
    return "City-Ready"

def require_admin_key():
    return request.headers.get("X-API-Key") == ADMIN_API_KEY

# --- Routes ---

# Homepage: intake form
@app.get("/")
def index():
    return render_template("index.html")

# Handle intake form submit
@app.post("/intake")
def intake():
    legal_name = request.form.get("legal_name","").strip()
    email = request.form.get("email","").strip()
    phone = request.form.get("phone","").strip()
    category = request.form.get("category","").strip()
    city = request.form.get("city","").strip()
    state = request.form.get("state","").strip()
    vendor_type = request.form.get("vendor_type","local")  # local / sub / prime
    kybkyc_choice = request.form.get("kybkyc","no")        # yes / no

    if not legal_name or not email:
        flash("Legal name and email are required","danger")
        return redirect(url_for("index"))

    v = Vendor(
        legal_name=legal_name,
        email=email,
        phone=phone,
        category=category,
        city=city,
        state=state,
        vendor_type=vendor_type,
        kybkyc=(kybkyc_choice=="yes")
    )
    db.session.add(v)
    db.session.commit()
    return redirect(url_for("upload_docs", vendor_id=v.id))

# Upload docs page
@app.get("/upload/<vendor_id>")
def upload_docs(vendor_id):
    v = Vendor.query.get_or_404(vendor_id)
    return render_template("upload.html", vendor=v, price=calc_price(v))

# Handle uploaded docs
@app.post("/upload/<vendor_id>")
def save_docs(vendor_id):
    v = Vendor.query.get_or_404(vendor_id)

    for kind in ["insurance","license","w9","policy"]:
        f = request.files.get(kind)
        if f and f.filename:
            filename = f"{vendor_id}_{kind}_{f.filename}"
            dest = os.path.join(app.config["UPLOAD_DIR"], filename)
            f.save(dest)
            d = Document(vendor_id=vendor_id, kind=kind, path=dest)
            db.session.add(d)

    db.session.commit()
    flash("Documents uploaded (or skipped).","success")
    return redirect(url_for("review", vendor_id=vendor_id))

# Review / payment summary page
@app.get("/review/<vendor_id>")
def review(vendor_id):
    v = Vendor.query.get_or_404(vendor_id)
    docs = Document.query.filter_by(vendor_id=vendor_id).all()
    score = compute_score(vendor_id)
    price = calc_price(v)
    return render_template(
        "review.html",
        vendor=v,
        docs=docs,
        score=score,
        price=price
    )

# Public verification page
@app.get("/verify/<vendor_id>")
def verify_page(vendor_id):
    v = Vendor.query.get_or_404(vendor_id)
    v.score = compute_score(vendor_id)
    db.session.commit()
    return render_template("verify.html", vendor=v, tier=tier_label(v))

# Admin: mark as paid + verify
@app.post("/admin/mark-paid/<vendor_id>")
def admin_mark_paid(vendor_id):
    if not require_admin_key():
        return jsonify({"error":"unauthorized"}), 401

    v = Vendor.query.get_or_404(vendor_id)
    v.paid = True
    v.score = compute_score(vendor_id)
    v.verified = (v.paid and v.score == 100)
    db.session.commit()

    return {
        "ok": True,
        "vendor_id": v.id,
        "paid": v.paid,
        "score": v.score,
        "verified": v.verified,
        "verify_url": url_for("verify_page", vendor_id=v.id, _external=True),
        "cert_url": url_for("cert_pdf", vendor_id=v.id, _external=True),
    }

# Certificate PDF
@app.get("/cert/<vendor_id>.pdf")
def cert_pdf(vendor_id):
    v = Vendor.query.get_or_404(vendor_id)

    if not v.verified:
        return "Not verified yet", 400

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 730, "CyberCore Verified Vendor Certificate")

    c.setFont("Helvetica", 12)
    c.drawString(72, 700, f"Vendor: {v.legal_name}")
    c.drawString(72, 680, f"Email: {v.email}")
    c.drawString(72, 660, f"Tier: {tier_label(v)}")
    c.drawString(72, 640, f"Score: {v.score}/100")
    c.drawString(72, 620, f"Status: VERIFIED ✅")
    c.drawString(72, 600, f"Issued: {datetime.utcnow().strftime('%Y-%m-%d')}")

    c.showPage()
    c.save()
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"cybercore_cert_{v.legal_name}.pdf",
        mimetype="application/pdf"
    )

if __name__ == "__main__":
    app.run(port=5000, debug=True)

