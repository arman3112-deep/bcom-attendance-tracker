import streamlit as st
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import math
import hashlib
import secrets

st.set_page_config(page_title="Attendance Tracker", page_icon="📚", layout="centered")
DB_FILE = "attendance.db"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def now_india():
    return datetime.now(ZoneInfo("Asia/Kolkata"))


def today_india():
    return now_india().date()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(":")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000).hex()
        return secrets.compare_digest(digest, digest_hex)
    except (ValueError, TypeError):
        return False


def get_connection():
    con = sqlite3.connect(DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            roll_number TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(student_name, roll_number, attendance_date, subject)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            day_name TEXT NOT NULL,
            lecture_no INTEGER NOT NULL,
            lecture_time TEXT NOT NULL,
            subject_code TEXT NOT NULL,
            subject_name TEXT NOT NULL,
            UNIQUE(student_id, day_name, lecture_no)
        )
    """)
    cols = {r[1] for r in con.execute("PRAGMA table_info(students)").fetchall()}
    for col in ("course", "division", "academic_year"):
        if col not in cols:
            con.execute(f"ALTER TABLE students ADD COLUMN {col} TEXT DEFAULT ''")
    con.commit()
    return con


def register_student(name, roll, password):
    con = get_connection()
    try:
        con.execute("INSERT INTO students(full_name, roll_number, password_hash, course, division, academic_year) VALUES(?,?,?,?,?,?)", (name, roll, hash_password(password), "", "", ""))
        con.commit()
        return True, "Account created successfully."
    except sqlite3.IntegrityError:
        return False, "This roll number is already registered."
    finally:
        con.close()


def login_student(roll, password):
    con = get_connection()
    row = con.execute("SELECT id, full_name, roll_number, password_hash, COALESCE(course,''), COALESCE(division,''), COALESCE(academic_year,'') FROM students WHERE roll_number=?", (roll,)).fetchone()
    con.close()
    if not row or not verify_password(password, row[3]):
        return None
    return {"id": row[0], "full_name": row[1], "roll_number": row[2], "course": row[4], "division": row[5], "academic_year": row[6]}


def update_profile(student_id, course, division, year):
    con = get_connection()
    con.execute("UPDATE students SET course=?, division=?, academic_year=? WHERE id=?", (course, division, year, student_id))
    con.commit()
    con.close()


def load_timetable(student_id):
    con = get_connection()
    rows = con.execute("SELECT day_name, lecture_no, lecture_time, subject_code, subject_name FROM timetable WHERE student_id=? ORDER BY CASE day_name WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 WHEN 'Sunday' THEN 7 END, lecture_no", (student_id,)).fetchall()
    con.close()
    result = {d: [] for d in DAYS}
    for row in rows:
        result[row[0]].append(row[1:])
    return result


def save_timetable(student_id, rows):
    con = get_connection()
    try:
        con.execute("DELETE FROM timetable WHERE student_id=?", (student_id,))
        for r in rows:
            con.execute("INSERT INTO timetable(student_id,day_name,lecture_no,lecture_time,subject_code,subject_name) VALUES(?,?,?,?,?,?)", (student_id, r["day_name"], r["lecture_no"], r["lecture_time"], r["subject_code"], r["subject_name"]))
        con.commit()
        return True, "Timetable saved successfully."
    except sqlite3.Error as e:
        con.rollback()
        return False, f"Could not save timetable: {e}"
    finally:
        con.close()


def save_attendance(name, roll, selected_date, data):
    if selected_date > today_india():
        return False, "Future dates cannot be saved."
    con = get_connection()
    try:
        for subject, status in data.items():
            con.execute("""
                INSERT INTO attendance(student_name,roll_number,attendance_date,subject,status)
                VALUES(?,?,?,?,?)
                ON CONFLICT(student_name,roll_number,attendance_date,subject)
                DO UPDATE SET status=excluded.status
            """, (name, roll, selected_date.isoformat(), subject, status))
        con.commit()
        return True, "Attendance saved successfully."
    except sqlite3.Error as e:
        con.rollback()
        return False, f"Could not save attendance: {e}"
    finally:
        con.close()


def load_attendance(name, roll):
    con = get_connection()
    df = pd.read_sql_query("SELECT attendance_date, subject, status FROM attendance WHERE student_name=? AND roll_number=? ORDER BY attendance_date DESC", con, params=(name, roll))
    con.close()
    return df


def needed_for_75(present, total):
    if total <= 0 or present / total >= 0.75:
        return 0
    return max(0, math.ceil((0.75 * total - present) / 0.25))


def can_miss_at_75(present, total):
    if total <= 0 or present / total < 0.75:
        return 0
    return max(0, math.floor(present / 0.75 - total))


def read_timetable(upload):
    try:
        if upload.name.lower().endswith(".csv"):
            df = pd.read_csv(upload)
        else:
            df = pd.read_excel(upload)
    except Exception as e:
        return None, f"Could not read file: {e}"
    df.columns = [str(c).strip().lower() for c in df.columns]
    def col(*names):
        for n in names:
            if n in df.columns:
                return n
        return None
    day_col = col("day", "day name", "weekday")
    subject_col = col("subject", "subject name", "class")
    lecture_col = col("lecture", "lecture no", "lecture number", "period", "period no")
    time_col = col("time", "lecture time", "timing")
    code_col = col("subject code", "code", "subject_code")
    if not day_col or not subject_col:
        return None, "The file must contain 'Day' and 'Subject' columns."
    rows = []
    for i, r in df.iterrows():
        day = str(r[day_col]).strip().title() if pd.notna(r[day_col]) else ""
        subject = str(r[subject_col]).strip() if pd.notna(r[subject_col]) else ""
        if not day or not subject:
            continue
        if day not in DAYS:
            return None, f"Invalid day on row {i + 2}: {day}"
        if lecture_col and pd.notna(r[lecture_col]):
            try:
                lecture_no = int(float(r[lecture_col]))
            except ValueError:
                lecture_no = len([x for x in rows if x["day_name"] == day]) + 1
        else:
            lecture_no = len([x for x in rows if x["day_name"] == day]) + 1
        lecture_time = str(r[time_col]).strip() if time_col and pd.notna(r[time_col]) else f"Lecture {lecture_no}"
        code = str(r[code_col]).strip() if code_col and pd.notna(r[code_col]) else subject[:12].upper()
        rows.append({"day_name": day, "lecture_no": lecture_no, "lecture_time": lecture_time, "subject_code": code, "subject_name": subject})
    return (rows, None) if rows else (None, "No timetable rows found.")


# Initialize database before UI.
get_connection().close()

for key, default in {"logged_in": False, "student_id": None, "student_name": "", "roll_number": "", "course": "", "division": "", "academic_year": ""}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# =====================================================
# LOGIN
# =====================================================

if not st.session_state.logged_in:
    st.title("📚 Attendance Tracker")
    st.caption("For any course • any division • any academic year")
    login_tab, create_tab = st.tabs(["🔐 Login", "📝 Create Account"])
    with login_tab:
        roll = st.text_input("Roll Number")
        password = st.text_input("Password", type="password")
        if st.button("🔐 Login", type="primary", width="stretch"):
            student = login_student(roll.strip(), password)
            if student:
                st.session_state.logged_in = True
                st.session_state.student_id = student["id"]
                st.session_state.student_name = student["full_name"]
                st.session_state.roll_number = student["roll_number"]
                st.session_state.course = student["course"]
                st.session_state.division = student["division"]
                st.session_state.academic_year = student["academic_year"]
                st.rerun()
            else:
                st.error("Invalid roll number or password.")
    with create_tab:
        name = st.text_input("Full Name")
        roll_new = st.text_input("Roll Number", key="new_roll")
        p1 = st.text_input("Create Password", type="password")
        p2 = st.text_input("Confirm Password", type="password")
        if st.button("📝 Create Account", type="primary", width="stretch"):
            name, roll_new = name.strip(), roll_new.strip()
            if not name or not roll_new or not p1:
                st.error("Please fill all required fields.")
            elif len(p1) < 6:
                st.error("Password must be at least 6 characters.")
            elif p1 != p2:
                st.error("Passwords do not match.")
            else:
                ok, msg = register_student(name, roll_new, p1)
                (st.success if ok else st.error)(msg)
    st.stop()


# =====================================================
# LOGGED-IN APP
# =====================================================

student_id = st.session_state.student_id
student_name = st.session_state.student_name
roll_number = st.session_state.roll_number

st.title("📚 Attendance Tracker")
parts = [x for x in [st.session_state.course, st.session_state.division, st.session_state.academic_year] if x]
st.caption(" • ".join(parts) if parts else "Set up your class details below.")

with st.sidebar:
    st.header("👤 My Account")
    st.write(f"**Name:** {student_name}")
    st.write(f"**Roll No.:** {roll_number}")
    if st.session_state.course:
        st.write(f"**Class:** {st.session_state.course}")
    if st.session_state.division:
        st.write(f"**Division:** {st.session_state.division}")
    if st.session_state.academic_year:
        st.write(f"**Year:** {st.session_state.academic_year}")
    if st.button("🚪 Logout", width="stretch"):
        for k in ["logged_in", "student_id", "student_name", "roll_number", "course", "division", "academic_year"]:
            st.session_state[k] = False if k == "logged_in" else (None if k == "student_id" else "")
        st.rerun()

setup_tab, attendance_tab, dashboard_tab, history_tab = st.tabs(["⚙️ Setup", "📝 Attendance", "📊 Dashboard", "📅 History"])


# =====================================================
# SETUP
# =====================================================

with setup_tab:
    st.header("⚙️ Class & Timetable Setup")
    st.info("Nothing is hard-coded to B.Com, M-2, 2026–27, or to any particular Wednesday/Thursday rule.")
    with st.form("profile"):
        course = st.text_input("Course / Class", value=st.session_state.course, placeholder="B.Com / BCA / BBA / Class 12")
        division = st.text_input("Division / Section", value=st.session_state.division, placeholder="M-2 / A / B")
        year = st.text_input("Academic Year", value=st.session_state.academic_year, placeholder="2026-27")
        save_profile = st.form_submit_button("💾 Save Class Details", type="primary", width="stretch")
    if save_profile:
        update_profile(student_id, course.strip(), division.strip(), year.strip())
        st.session_state.course = course.strip()
        st.session_state.division = division.strip()
        st.session_state.academic_year = year.strip()
        st.success("Class details saved.")
        st.rerun()

    st.divider()
    st.subheader("📤 Upload Timetable")
    st.write("CSV or Excel columns: **Day, Lecture, Time, Subject Code, Subject**. You can have 3, 4, or any number of lectures per day.")
    template = pd.DataFrame([
        ["Monday", 1, "09:00-10:00", "FA", "Financial Accounting"],
        ["Monday", 2, "10:00-11:00", "SPB", "Business"],
        ["Tuesday", 1, "09:00-10:00", "BSC", "Statistics"],
    ], columns=["Day", "Lecture", "Time", "Subject Code", "Subject"])
    st.download_button("⬇️ Download Timetable Template", template.to_csv(index=False).encode(), "timetable_template.csv", "text/csv", width="stretch")
    upload = st.file_uploader("Upload CSV or Excel timetable", type=["csv", "xlsx", "xls"])
    if upload:
        rows, error = read_timetable(upload)
        if error:
            st.error(error)
        else:
            preview = pd.DataFrame(rows).rename(columns={"day_name": "Day", "lecture_no": "Lecture", "lecture_time": "Time", "subject_code": "Subject Code", "subject_name": "Subject"})
            st.dataframe(preview, width="stretch", hide_index=True)
            if st.button("💾 Save Uploaded Timetable", type="primary", width="stretch"):
                ok, msg = save_timetable(student_id, rows)
                (st.success if ok else st.error)(msg)
                if ok:
                    st.rerun()

    st.divider()
    st.subheader("✏️ Manual Timetable")
    current = load_timetable(student_id)
    manual = []
    for day in DAYS:
        with st.expander(day, expanded=(day == "Monday")):
            old = current.get(day, [])
            count = st.number_input(f"Lectures on {day}", 0, 12, len(old), 1, key=f"count_{day}")
            for i in range(int(count)):
                oldrow = old[i] if i < len(old) else ("", "", "")
                c1, c2, c3 = st.columns([1.4, 1.2, 2.5])
                with c1:
                    t = st.text_input("Time", value=oldrow[1], key=f"time_{day}_{i}")
                with c2:
                    code = st.text_input("Code", value=oldrow[2], key=f"code_{day}_{i}")
                with c3:
                    subj = st.text_input("Subject", value=oldrow[3], key=f"subj_{day}_{i}")
                if subj.strip():
                    manual.append({"day_name": day, "lecture_no": i + 1, "lecture_time": t.strip() or f"Lecture {i + 1}", "subject_code": code.strip() or subj.strip()[:12].upper(), "subject_name": subj.strip()})
    if st.button("💾 Save Manual Timetable", type="primary", width="stretch"):
        ok, msg = save_timetable(student_id, manual)
        (st.success if ok else st.error)(msg)
        if ok:
            st.rerun()

    current = load_timetable(student_id)
    rows = []
    for day in DAYS:
        for no, tm, code, subj in current.get(day, []):
            rows.append({"Day": day, "Lecture": no, "Time": tm, "Code": code, "Subject": subj})
    if rows:
        st.subheader("✅ Current Timetable")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# =====================================================
# ATTENDANCE
# =====================================================

with attendance_tab:
    st.header("📝 Mark Attendance")
    current_date = today_india()
    st.info(f"📅 Today's date: {current_date.strftime('%A, %d %B %Y')}")
    selected = st.date_input("Select Date", value=current_date, max_value=current_date, help="Today and past dates are allowed. Future dates are blocked.")
    if selected > current_date:
        st.error("🚫 Future dates are not allowed.")
        st.stop()
    day = selected.strftime("%A")
    st.subheader(f"📅 {day}, {selected.strftime('%d %B %Y')}")
    st.success("🟢 Today's attendance." if selected == current_date else "📖 Past-date mode: view or update attendance.")
    classes = load_timetable(student_id).get(day, [])
    if not classes:
        st.info(f"No classes are configured for {day}. Open Setup → Timetable.")
    else:
        holiday = st.checkbox("🟡 College Holiday — whole day", key=f"holiday_{selected}")
        attendance = {}
        for no, tm, code, subj in classes:
            st.divider()
            st.markdown(f"### Lecture {no} — {tm}")
            st.write(f"**{code} — {subj}**")
            key = f"{code} — {subj}"
            if holiday:
                attendance[key] = "Holiday"
                st.warning("🟡 College Holiday — not counted.")
            else:
                attendance[key] = st.radio("Status", ["Present", "Absent", "Holiday"], horizontal=True, key=f"status_{selected}_{no}_{code}")
        st.divider()
        if st.button("💾 Save Attendance", type="primary", width="stretch"):
            ok, msg = save_attendance(student_name, roll_number, selected, attendance)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()


# =====================================================
# DASHBOARD
# =====================================================

with dashboard_tab:
    st.header("📊 Attendance Dashboard")
    data = load_attendance(student_name, roll_number)
    if data.empty:
        st.info("No attendance recorded yet.")
    else:
        conducted = data[data.status != "Holiday"]
        present = len(data[data.status == "Present"])
        absent = len(data[data.status == "Absent"])
        total = len(conducted)
        overall = (present / total * 100) if total else 0
        a, b, c = st.columns(3)
        a.metric("Overall", f"{overall:.1f}%")
        b.metric("Present", present)
        c.metric("Absent", absent)
        st.divider()
        timetable = load_timetable(student_id)
        subjects = []
        for day in DAYS:
            for _, _, code, subj in timetable.get(day, []):
                label = f"{code} — {subj}"
                if label not in subjects:
                    subjects.append(label)
        for value in data.subject.dropna().unique():
            if value not in subjects:
                subjects.append(value)
        report = []
        for subject in subjects:
            d = data[data.subject == subject]
            p = len(d[d.status == "Present"])
            ab = len(d[d.status == "Absent"])
            h = len(d[d.status == "Holiday"])
            t = p + ab
            pct = p / t * 100 if t else 0
            report.append({"Subject": subject, "Present": p, "Absent": ab, "Holiday": h, "Total": t, "Attendance %": round(pct, 1), "Need for 75%": needed_for_75(p, t), "Can Miss": can_miss_at_75(p, t)})
        st.subheader("📚 Subject-wise Attendance")
        st.dataframe(pd.DataFrame(report), width="stretch", hide_index=True)
        st.subheader("🎯 75% Attendance Planner")
        planner = []
        for r in report:
            if r["Total"] == 0:
                text = "No classes recorded"
            elif r["Attendance %"] < 75:
                text = f"Attend next {r['Need for 75%']} class(es) continuously"
            else:
                text = f"You can miss {r['Can Miss']} class(es) and stay ≥ 75%"
            planner.append({"Subject": r["Subject"], "Current %": r["Attendance %"], "Present": r["Presen
