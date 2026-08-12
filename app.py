import streamlit as st
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import math
import hashlib
import secrets
import io
import os
import json
import re

# Optional readers. The app still works if some of these packages are not installed.
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from docx import Document
except Exception:
    Document = None

st.set_page_config(
    page_title="Attendance Tracker",
    page_icon="📚",
    layout="centered",
)

DB_FILE = "attendance.db"

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

DAY_ALIASES = {
    "mon": "Monday",
    "monday": "Monday",
    "tue": "Tuesday",
    "tues": "Tuesday",
    "tuesday": "Tuesday",
    "wed": "Wednesday",
    "wednesday": "Wednesday",
    "thu": "Thursday",
    "thur": "Thursday",
    "thurs": "Thursday",
    "thursday": "Thursday",
    "fri": "Friday",
    "friday": "Friday",
    "sat": "Saturday",
    "saturday": "Saturday",
    "sun": "Sunday",
    "sunday": "Sunday",
}


# =====================================================
# DATE / PASSWORD HELPERS
# =====================================================

def now_india():
    return datetime.now(ZoneInfo("Asia/Kolkata"))


def today_india():
    return now_india().date()


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        200_000,
    )
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(":")
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            200_000,
        ).hex()
        return secrets.compare_digest(digest, digest_hex)
    except (ValueError, TypeError):
        return False


# =====================================================
# DATABASE
# =====================================================

def get_connection():
    con = sqlite3.connect(DB_FILE, timeout=30)

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            roll_number TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(student_name, roll_number, attendance_date, subject)
        )
        """
    )

    con.execute(
        """
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
        """
    )

    # Upgrade old databases without losing existing data.
    cols = {
        row[1]
        for row in con.execute("PRAGMA table_info(students)").fetchall()
    }

    for col in ("course", "division", "academic_year"):
        if col not in cols:
            con.execute(
                f"ALTER TABLE students ADD COLUMN {col} TEXT DEFAULT ''"
            )

    con.commit()
    return con


def register_student(name, roll, password):
    con = get_connection()
    try:
        con.execute(
            """
            INSERT INTO students
            (full_name, roll_number, password_hash, course, division, academic_year)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                roll,
                hash_password(password),
                "",
                "",
                "",
            ),
        )
        con.commit()
        return True, "Account created successfully."
    except sqlite3.IntegrityError:
        return False, "This roll number is already registered."
    finally:
        con.close()


def login_student(roll, password):
    con = get_connection()

    row = con.execute(
        """
        SELECT
            id,
            full_name,
            roll_number,
            password_hash,
            COALESCE(course, ''),
            COALESCE(division, ''),
            COALESCE(academic_year, '')
        FROM students
        WHERE roll_number = ?
        """,
        (roll,),
    ).fetchone()

    con.close()

    if not row or not verify_password(password, row[3]):
        return None

    return {
        "id": row[0],
        "full_name": row[1],
        "roll_number": row[2],
        "course": row[4],
        "division": row[5],
        "academic_year": row[6],
    }


def update_profile(student_id, course, division, year):
    con = get_connection()
    con.execute(
        """
        UPDATE students
        SET course = ?, division = ?, academic_year = ?
        WHERE id = ?
        """,
        (
            course,
            division,
            year,
            student_id,
        ),
    )
    con.commit()
    con.close()


# =====================================================
# TIMETABLE
# =====================================================

def load_timetable(student_id):
    con = get_connection()

    rows = con.execute(
        """
        SELECT
            day_name,
            lecture_no,
            lecture_time,
            subject_code,
            subject_name
        FROM timetable
        WHERE student_id = ?
        ORDER BY
            CASE day_name
                WHEN 'Monday' THEN 1
                WHEN 'Tuesday' THEN 2
                WHEN 'Wednesday' THEN 3
                WHEN 'Thursday' THEN 4
                WHEN 'Friday' THEN 5
                WHEN 'Saturday' THEN 6
                WHEN 'Sunday' THEN 7
            END,
            lecture_no
        """,
        (student_id,),
    ).fetchall()

    con.close()

    result = {day: [] for day in DAYS}

    for row in rows:
        if row[0] in result:
            result[row[0]].append(row[1:])

    return result


def save_timetable(student_id, rows):
    con = get_connection()

    try:
        con.execute(
            "DELETE FROM timetable WHERE student_id = ?",
            (student_id,),
        )

        for row in rows:
            con.execute(
                """
                INSERT INTO timetable
                (
                    student_id,
                    day_name,
                    lecture_no,
                    lecture_time,
                    subject_code,
                    subject_name
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    student_id,
                    row["day_name"],
                    int(row["lecture_no"]),
                    row["lecture_time"],
                    row["subject_code"],
                    row["subject_name"],
                ),
            )

        con.commit()
        return True, "Timetable saved successfully."

    except sqlite3.Error as error:
        con.rollback()
        return False, f"Could not save timetable: {error}"

    finally:
        con.close()


def normalize_day(value):
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)

    if text in DAY_ALIASES:
        return DAY_ALIASES[text]

    # Handles values such as "Monday 1", "Mon", etc.
    first_word = text.split()[0] if text.split() else ""
    return DAY_ALIASES.get(first_word, str(value).strip().title())


def clean_cell(value):
    if value is None:
        return ""

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "nat"}:
        return ""

    return text


def find_column(columns, aliases):
    normalized = {
        str(c).strip().lower().replace("_", " "): c
        for c in columns
    }

    for alias in aliases:
        alias_normalized = alias.lower().replace("_", " ")
        if alias_normalized in normalized:
            return normalized[alias_normalized]

    # More flexible matching.
    for col in columns:
        col_text = str(col).strip().lower().replace("_", " ")
        for alias in aliases:
            alias_text = alias.lower().replace("_", " ")
            if alias_text in col_text or col_text in alias_text:
                return col

    return None


def dataframe_to_timetable(df):
    if df is None or df.empty:
        return None, "No timetable data was found."

    df = df.copy()
    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    day_col = find_column(
        df.columns,
        ["day", "day name", "weekday", "week day"],
    )

    subject_col = find_column(
        df.columns,
        [
            "subject",
            "subject name",
            "class",
            "course",
            "paper",
            "lecture subject",
        ],
    )

    lecture_col = find_column(
        df.columns,
        [
            "lecture",
            "lecture no",
            "lecture number",
            "period",
            "period no",
            "period number",
            "slot",
        ],
    )

    time_col = find_column(
        df.columns,
        [
            "time",
            "lecture time",
            "timing",
            "time slot",
            "period time",
        ],
    )

    code_col = find_column(
        df.columns,
        [
            "subject code",
            "code",
            "subject_code",
            "paper code",
        ],
    )

    if not day_col or not subject_col:
        return (
            None,
            "I could not find Day and Subject columns. "
            "Use the manual timetable below or upload a table containing Day + Subject.",
        )

    rows = []
    day_counts = {day: 0 for day in DAYS}

    for index, row in df.iterrows():
        day = normalize_day(row.get(day_col, ""))
        subject = clean_cell(row.get(subject_col, ""))

        if not subject:
            continue

        if day not in DAYS:
            continue

        lecture_raw = (
            clean_cell(row.get(lecture_col, ""))
            if lecture_col
            else ""
        )

        lecture_no = None

        if lecture_raw:
            try:
                lecture_no = int(float(lecture_raw))
            except Exception:
                match = re.search(r"\d+", lecture_raw)
                if match:
                    lecture_no = int(match.group())

        if not lecture_no:
            day_counts[day] += 1
            lecture_no = day_counts[day]
        else:
            day_counts[day] = max(
                day_counts[day],
                lecture_no,
            )

        time_value = (
            clean_cell(row.get(time_col, ""))
            if time_col
            else ""
        )

        if not time_value:
            time_value = f"Lecture {lecture_no}"

        code = (
            clean_cell(row.get(code_col, ""))
            if code_col
            else ""
        )

        if not code:
            code = re.sub(
                r"[^A-Za-z0-9]+",
                "",
                subject,
            )[:12].upper() or f"S{lecture_no}"

        rows.append(
            {
                "day_name": day,
                "lecture_no": lecture_no,
                "lecture_time": time_value,
                "subject_code": code,
                "subject_name": subject,
            }
        )

    if not rows:
        return None, "No valid timetable rows were found."

    # Prevent duplicate lecture numbers within a day.
    used = {day: set() for day in DAYS}
    final_rows = []

    for row in rows:
        day = row["day_name"]
        no = row["lecture_no"]

        if no in used[day]:
            no = 1
            while no in used[day]:
                no += 1
            row["lecture_no"] = no

        used[day].add(row["lecture_no"])
        final_rows.append(row)

    final_rows.sort(
        key=lambda r: (
            DAYS.index(r["day_name"]),
            r["lecture_no"],
        )
    )

    return final_rows, None


def parse_text_timetable(text):
    """
    Best-effort parser for TXT/CSV-like files and pasted timetable text.
    It looks for lines containing a weekday and a subject.
    """
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    rows = []
    counters = {day: 0 for day in DAYS}

    for line in lines:
        # Split common table separators.
        parts = [
            p.strip()
            for p in re.split(r"\t+|\s{2,}|\|+|;", line)
            if p.strip()
        ]

        if len(parts) < 2:
            continue

        day = normalize_day(parts[0])

        if day not in DAYS:
            continue

        # Try to identify a subject from the remaining cells.
        remaining = parts[1:]

        lecture_no = None
        time_value = ""
        code = ""
        subject = ""

        for part in remaining:
            if not lecture_no:
                match = re.fullmatch(r"(?:lecture|period|slot)?\s*(\d+)", part, re.I)
                if match:
                    lecture_no = int(match.group(1))
                    continue

            if not time_value and re.search(r"\d{1,2}[:.]\d{2}", part):
                time_value = part
                continue

            if not code and re.fullmatch(r"[A-Za-z]{1,8}[-_/]?\d{0,5}", part):
                code = part
                continue

            if not subject:
                subject = part

        if not subject and remaining:
            subject = remaining[-1]

        if not subject:
            continue

        if not lecture_no:
            counters[day] += 1
            lecture_no = counters[day]
        else:
            counters[day] = max(
                counters[day],
                lecture_no,
            )

        if not time_value:
            time_value = f"Lecture {lecture_no}"

        if not code:
            code = re.sub(
                r"[^A-Za-z0-9]+",
                "",
                subject,
            )[:12].upper()

        rows.append(
            {
                "day_name": day,
                "lecture_no": lecture_no,
                "lecture_time": time_value,
                "subject_code": code or f"S{lecture_no}",
                "subject_name": subject,
            }
        )

    if rows:
        return dataframe_to_timetable(
            pd.DataFrame(
                [
                    {
                        "Day": r["day_name"],
                        "Lecture": r["lecture_no"],
                        "Time": r["lecture_time"],
                        "Subject Code": r["subject_code"],
                        "Subject": r["subject_name"],
                    }
                    for r in rows
                ]
            )
        )

    return None, "No timetable rows could be detected from this text file."


def read_timetable(upload):
    """
    Accepts every file extension in the uploader.

    Automatic timetable reading:
    - CSV / TSV
    - Excel XLS/XLSX
    - JSON
    - HTML
    - TXT
    - PDF when pypdf is installed
    - DOCX when python-docx is installed

    Other files are still allowed to upload, but the app cannot
    reliably understand every binary/image format automatically.
    """
    filename = (upload.name or "").lower()
    extension = os.path.splitext(filename)[1]

    try:
        raw = upload.getvalue()

        if extension in {".csv", ".tsv"}:
            separator = "\t" if extension == ".tsv" else ","

            try:
                df = pd.read_csv(
                    io.BytesIO(raw),
                    sep=separator,
                )
            except Exception:
                df = pd.read_csv(
                    io.BytesIO(raw),
                    sep=None,
                    engine="python",
                )

            return dataframe_to_timetable(df)

        if extension in {".xlsx", ".xls", ".xlsm"}:
            # First sheet is used.
            sheets = pd.read_excel(
                io.BytesIO(raw),
                sheet_name=None,
            )

            if not sheets:
                return None, "No worksheet was found."

            # Pick the sheet with the most useful rows.
            best_df = max(
                sheets.values(),
                key=lambda x: len(x),
            )

            return dataframe_to_timetable(best_df)

        if extension == ".json":
            data = json.loads(
                raw.decode("utf-8-sig")
            )

            if isinstance(data, dict):
                # Common form: {"Monday": [...], ...}
                if any(
                    normalize_day(key) in DAYS
                    for key in data.keys()
                ):
                    table_rows = []

                    for day_key, values in data.items():
                        day = normalize_day(day_key)

                        if day not in DAYS:
                            continue

                        if isinstance(values, list):
                            for i, value in enumerate(values, 1):
                                if isinstance(value, dict):
                                    table_rows.append(
                                        {
                                            "Day": day,
                                            "Lecture": value.get(
                                                "Lecture",
                                                value.get("lecture", i),
                                            ),
                                            "Time": value.get(
                                                "Time",
                                                value.get("time", ""),
                                            ),
                                            "Subject Code": value.get(
                                                "Subject Code",
                                                value.get("code", ""),
                                            ),
                                            "Subject": value.get(
                                                "Subject",
                                                value.get("subject", ""),
                                            ),
                                        }
                                    )
                                else:
                                    table_rows.append(
                                        {
                                            "Day": day,
                                            "Lecture": i,
                                            "Time": "",
                                            "Subject Code": "",
                                            "Subject": str(value),
                                        }
                                    )

                    if table_rows:
                        return dataframe_to_timetable(
                            pd.DataFrame(table_rows)
                        )

            if isinstance(data, list):
                return dataframe_to_timetable(
                    pd.DataFrame(data)
                )

            return None, "JSON format was not recognized as a timetable."

        if extension in {".html", ".htm"}:
            tables = pd.read_html(io.BytesIO(raw))

            if not tables:
                return None, "No table was found in the HTML file."

            best_df = max(
                tables,
                key=lambda x: len(x),
            )

            return dataframe_to_timetable(best_df)

        if extension in {".txt", ".text"}:
            text = raw.decode(
                "utf-8",
                errors="ignore",
            )
            return parse_text_timetable(text)

        if extension == ".pdf":
            if PdfReader is None:
                return (
                    None,
                    "PDF was uploaded, but PDF reading is not installed in this app. "
                    "Use the Manual Timetable section or add pypdf to requirements.txt.",
                )

            reader = PdfReader(io.BytesIO(raw))
            text = "\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )

            if not text.strip():
                return (
                    None,
                    "This PDF appears to contain an image/scanned timetable. "
                    "Automatic OCR is not enabled; use the Manual Timetable section.",
                )

            return parse_text_timetable(text)

        if extension == ".docx":
            if Document is None:
                return (
                    None,
                    "DOCX was uploaded, but Word-file reading is not installed. "
                    "Use the Manual Timetable section or add python-docx to requirements.txt.",
                )

            document = Document(io.BytesIO(raw))

            table_frames = []

            for table in document.tables:
                data = [
                    [
                        cell.text.strip()
                        for cell in row.cells
                    ]
                    for row in table.rows
                ]

                if len(data) >= 2:
                    table_frames.append(
                        pd.DataFrame(
                            data[1:],
                            columns=data[0],
                        )
                    )

            if table_frames:
                best_df = max(
                    table_frames,
                    key=lambda x: len(x),
                )
                result = dataframe_to_timetable(best_df)

                if result[0]:
                    return result

            paragraph_text = "\n".join(
                p.text
                for p in document.paragraphs
                if p.text.strip()
            )

            return parse_text_timetable(
                paragraph_text
            )

        # All other formats are accepted by the uploader.
        return (
            None,
            f"'{upload.name}' was uploaded successfully, "
            "but this file format cannot be automatically converted into a timetable. "
            "Use the Manual Timetable section below, or upload CSV/Excel/PDF/DOCX/TXT/JSON/HTML.",
        )

    except Exception as error:
        return None, f"Could not read the timetable file: {error}"


# =====================================================
# ATTENDANCE
# =====================================================

def save_attendance(
    name,
    roll,
    selected_date,
    attendance_data,
):
    # Server-side future-date protection.
    if selected_date > today_india():
        return False, "Future dates cannot be saved."

    con = get_connection()

    try:
        for subject, status in attendance_data.items():
            con.execute(
                """
                INSERT INTO attendance
                (
                    student_name,
                    roll_number,
                    attendance_date,
                    subject,
                    status
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(
                    student_name,
                    roll_number,
                    attendance_date,
                    subject
                )
                DO UPDATE SET
                    status = excluded.status
                """,
                (
                    name,
                    roll,
                    selected_date.isoformat(),
                    subject,
                    status,
                ),
            )

        con.commit()
        return True, "Attendance saved successfully."

    except sqlite3.Error as error:
        con.rollback()
        return False, f"Could not save attendance: {error}"

    finally:
        con.close()


def load_attendance(name, roll):
    con = get_connection()

    df = pd.read_sql_query(
        """
        SELECT
            attendance_date,
            subject,
            status
        FROM attendance
        WHERE student_name = ?
          AND roll_number = ?
        ORDER BY attendance_date DESC
        """,
        con,
        params=(
            name,
            roll,
        ),
    )

    con.close()
    return df


# =====================================================
# 75% CALCULATIONS
# =====================================================

def needed_for_75(present, total):
    if total <= 0 or present / total >= 0.75:
        return 0

    return max(
        0,
        math.ceil(
            (0.75 * total - present) / 0.25
        ),
    )


def can_miss_at_75(present, total):
    if total <= 0 or present / total < 0.75:
        return 0

    return max(
        0,
        math.floor(
            present / 0.75 - total
        ),
    )


# =====================================================
# INITIALIZE DATABASE
# =====================================================

get_connection().close()


# =====================================================
# SESSION STATE
# =====================================================

DEFAULT_STATE = {
    "logged_in": False,
    "student_id": None,
    "student_name": "",
    "roll_number": "",
    "course": "",
    "division": "",
    "academic_year": "",
}

for key, default in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = default


# =====================================================
# LOGIN / CREATE ACCOUNT
# =====================================================

if not st.session_state.logged_in:
    st.title("📚 Attendance Tracker")
    st.caption(
        "For any course • any division • any academic year"
    )

    login_tab, create_tab = st.tabs(
        [
            "🔐 Login",
            "📝 Create Account",
        ]
    )

    with login_tab:
        st.subheader("Login to your account")

        roll = st.text_input(
            "Roll Number",
            key="login_roll",
        )

        password = st.text_input(
            "Password",
            type="password",
            key="login_password",
        )

        if st.button(
            "🔐 Login",
            type="primary",
            width="stretch",
        ):
            student = login_student(
                roll.strip(),
                password,
            )

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
                st.error(
                    "Invalid roll number or password."
                )

    with create_tab:
        st.subheader("Create your account")

        name = st.text_input(
            "Full Name",
            key="create_name",
        )

        roll_new = st.text_input(
            "Roll Number",
            key="create_roll",
        )

        p1 = st.text_input(
            "Create Password",
            type="password",
            key="create_password",
        )

        p2 = st.text_input(
            "Confirm Password",
            type="password",
            key="confirm_password",
        )

        if st.button(
            "📝 Create Account",
            type="primary",
            width="stretch",
        ):
            name = name.strip()
            roll_new = roll_new.strip()

            if not name or not roll_new or not p1:
                st.error(
                    "Please fill all required fields."
                )

            elif len(p1) < 6:
                st.error(
                    "Password must be at least 6 characters."
                )

            elif p1 != p2:
                st.error(
                    "Passwords do not match."
                )

            else:
                ok, msg = register_student(
                    name,
                    roll_new,
                    p1,
                )

                (
                    st.success
                    if ok
                    else st.error
                )(msg)

    st.stop()


# =====================================================
# LOGGED-IN APP
# =====================================================

student_id = st.session_state.student_id
student_name = st.session_state.student_name
roll_number = st.session_state.roll_number

st.title("📚 Attendance Tracker")

parts = [
    value
    for value in [
        st.session_state.course,
        st.session_state.division,
        st.session_state.academic_year,
    ]
    if value
]

if parts:
    st.caption(" • ".join(parts))
else:
    st.caption("Set up your class details below.")


# =====================================================
# SIDEBAR
# =====================================================

with st.sidebar:
    st.header("👤 My Account")

    st.write(
        f"**Name:** {student_name}"
    )

    st.write(
        f"**Roll No.:** {roll_number}"
    )

    if st.session_state.course:
        st.write(
            f"**Class:** {st.session_state.course}"
        )

    if st.session_state.division:
        st.write(
            f"**Division:** {st.session_state.division}"
        )

    if st.session_state.academic_year:
        st.write(
            f"**Academic Year:** {st.session_state.academic_year}"
        )

    if st.button(
        "🚪 Logout",
        width="stretch",
    ):
        st.session_state.logged_in = False
        st.session_state.student_id = None
        st.session_state.student_name = ""
        st.session_state.roll_number = ""
        st.session_state.course = ""
        st.session_state.division = ""
        st.session_state.academic_year = ""
        st.rerun()


setup_tab, attendance_tab, dashboard_tab, history_tab = st.tabs(
    [
        "⚙️ Setup",
        "📝 Attendance",
        "📊 Dashboard",
        "📅 History",
    ]
)


# =====================================================
# SETUP
# =====================================================

with setup_tab:
    st.header("⚙️ Class & Timetable Setup")

    # No hard-coded B.Com / M-2 / year / weekday rule.

    with st.form("profile"):
        course = st.text_input(
            "Course / Class",
            value=st.session_state.course,
            placeholder="B.Com / BCA / BBA / Class 12",
        )

        division = st.text_input(
            "Division / Section",
            value=st.session_state.division,
            placeholder="M-2 / A / B",
        )

        year = st.text_input(
            "Academic Year",
            value=st.session_state.academic_year,
            placeholder="2026-27",
        )

        save_profile = st.form_submit_button(
            "💾 Save Class Details",
            type="primary",
            width="stretch",
        )

    if save_profile:
        update_profile(
            student_id,
            course.strip(),
            division.strip(),
            year.strip(),
        )

        st.session_state.course = course.strip()
        st.session_state.division = division.strip()
        st.session_state.academic_year = year.strip()

        st.success(
            "Class details saved."
        )

        st.rerun()

    st.divider()

    # -------------------------------------------------
    # TIMETABLE UPLOAD
    # -------------------------------------------------

    st.subheader("📤 Upload Timetable")

    st.write(
        "You can upload any file type. "
        "CSV, Excel, TXT, JSON, HTML, PDF and DOCX "
        "have automatic readers when their required reader is available."
    )

    st.caption(
        "For the most reliable automatic import, use a table with "
        "Day + Subject columns."
    )

    template = pd.DataFrame(
        [
            [
                "Monday",
                1,
                "09:00-10:00",
                "FA",
                "Financial Accounting",
            ],
            [
                "Monday",
                2,
                "10:00-11:00",
                "SPB",
                "Business",
            ],
            [
                "Tuesday",
                1,
                "09:00-10:00",
                "BSC",
                "Statistics",
            ],
            [
                "Tuesday",
                2,
                "10:00-11:00",
                "EET",
                "Economics",
            ],
        ],
        columns=[
            "Day",
            "Lecture",
            "Time",
            "Subject Code",
            "Subject",
        ],
    )

    st.download_button(
        "⬇️ Download Timetable Template",
        template.to_csv(index=False).encode("utf-8"),
        "timetable_template.csv",
        "text/csv",
        width="stretch",
    )

    upload = st.file_uploader(
        "Choose your timetable file",
        type=None,
        accept_multiple_files=False,
        key="timetable_upload",
        help=(
            "All file extensions are allowed. "
            "Automatic reading works best with CSV/Excel."
        ),
    )

    if upload is not None:
        file_size_mb = upload.size / (1024 * 1024)

        st.caption(
            f"Selected file: {upload.name} • "
            f"{file_size_mb:.2f} MB"
        )

        rows, error = read_timetable(upload)

        if error:
            st.warning(error)

        if rows:
            preview = pd.DataFrame(rows).rename(
                columns={
                    "day_name": "Day",
                    "lecture_no": "Lecture",
                    "lecture_time": "Time",
                    "subject_code": "Subject Code",
                    "subject_name": "Subject",
                }
            )

            st.subheader("👀 Timetable Preview")
            st.dataframe(
                preview,
                width="stretch",
                hide_index=True,
            )

            st.success(
                f"{len(rows)} timetable lecture(s) detected."
            )

            if st.button(
                "💾 Save Uploaded Timetable",
                type="primary",
                width="stretch",
            ):
                ok, msg = save_timetable(
                    student_id,
                    rows,
                )

                (
                    st.success
                    if ok
                    else st.error
                )(msg)

                if ok:
                    st.rerun()

    # -------------------------------------------------
    # MANUAL TIMETABLE
    # -------------------------------------------------

    st.divider()
    st.subheader("✏️ Manual Timetable")

    st.caption(
        "Use this if your uploaded timetable is a photo, scanned PDF, "
        "or another format that cannot be read automatically."
    )

    current = load_timetable(student_id)
    manual = []

    for day in DAYS:
        with st.expander(
            day,
            expanded=(day == "Monday"),
        ):
            old = current.get(day, [])

            count = st.number_input(
                f"Lectures on {day}",
                min_value=0,
                max_value=30,
                value=len(old),
                step=1,
                key=f"count_{day}",
            )

            for i in range(int(count)):
                # Correct 4-field fallback:
                # time, code, subject are stored after lecture number.
                if i < len(old):
                    oldrow = old[i]
                else:
                    oldrow = (
                        i + 1,
                        "",
                        "",
                        "",
                    )

                c1, c2, c3 = st.columns(
                    [1.4, 1.2, 2.5]
                )

                with c1:
                    time_value = st.text_input(
                        "Time",
                        value=str(oldrow[1]),
                        key=f"time_{day}_{i}",
                    )

                with c2:
                    code = st.text_input(
                        "Code",
                        value=str(oldrow[2]),
                        key=f"code_{day}_{i}",
                    )

                with c3:
                    subject = st.text_input(
                        "Subject",
                        value=str(oldrow[3]),
                        key=f"subj_{day}_{i}",
                    )

                if subject.strip():
                    manual.append(
                        {
                            "day_name": day,
                            "lecture_no": i + 1,
                            "lecture_time": (
                                time_value.strip()
                                or f"Lecture {i + 1}"
                            ),
                            "subject_code": (
                                code.strip()
                                or re.sub(
                                    r"[^A-Za-z0-9]+",
                                    "",
                                    subject.strip(),
                                )[:12].upper()
                                or f"S{i + 1}"
                            ),
                            "subject_name": subject.strip(),
                        }
                    )

    if st.button(
        "💾 Save Manual Timetable",
        type="primary",
        width="stretch",
    ):
        ok, msg = save_timetable(
            student_id,
            manual,
        )

        (
            st.success
            if ok
            else st.error
        )(msg)

        if ok:
            st.rerun()

    # -------------------------------------------------
    # CURRENT TIMETABLE
    # -------------------------------------------------

    current = load_timetable(student_id)

    rows_for_display = []

    for day in DAYS:
        for no, tm, code, subj in current.get(day, []):
            rows_for_display.append(
                {
                    "Day": day,
                    "Lecture": no,
                    "Time": tm,
                    "Code": code,
                    "Subject": subj,
                }
            )

    if rows_for_display:
        st.subheader("✅ Current Timetable")

        st.dataframe(
            pd.DataFrame(rows_for_display),
            width="stretch",
            hide_index=True,
        )


# =====================================================
# ATTENDANCE
# =====================================================

with attendance_tab:
    st.header("📝 Mark Attendance")

    current_date = today_india()

    st.write(
        f"📅 **Today:** "
        f"{current_date.strftime('%A, %d %B %Y')}"
    )

    # max_value blocks future dates in the UI.
    # The save_attendance() function also checks it on the server.
    selected = st.date_input(
        "Select Date",
        value=current_date,
        max_value=current_date,
        help="Today and past dates are allowed. Future dates are blocked.",
    )

    if selected > current_date:
        st.error(
            "🚫 Future dates are not allowed."
        )
        st.stop()

    day = selected.strftime("%A")

    st.subheader(
        f"📅 {day}, "
        f"{selected.strftime('%d %B %Y')}"
    )

    if selected == current_date:
        st.success(
            "🟢 Today's attendance"
        )
    else:
        st.info(
            "📖 Past-date mode: you can view or update attendance."
        )

    classes = load_timetable(
        student_id
    ).get(day, [])

    if not classes:
        st.warning(
            f"No classes are configured for {day}. "
            "Open Setup → Manual Timetable or upload your timetable."
        )

    else:
        holiday = st.checkbox(
            "🟡 College Holiday — whole day",
            key=f"holiday_{selected}",
        )

        attendance = {}

        for no, tm, code, subj in classes:
            st.divider()

            st.markdown(
                f"### Lecture {no} — {tm}"
            )

            st.write(
                f"**{code} — {subj}**"
            )

            key = f"{code} — {subj}"

            if holiday:
                attendance[key] = "Holiday"

            else:
                attendance[key] = st.radio(
                    "Status",
                    [
                        "Present",
                        "Absent",
                        "Holiday",
                    ],
                    horizontal=True,
                    key=f"status_{selected}_{no}_{code}",
                )

        st.divider()

        if st.button(
            "💾 Save Attendance",
            type="primary",
            width="stretch",
        ):
            ok, msg = save_attendance(
                student_name,
                roll_number,
                selected,
                attendance,
            )

            (
                st.success
                if ok
                else st.error
            )(msg)

            if ok:
                st.rerun()


# =====================================================
# DASHBOARD
# =====================================================

with dashboard_tab:
    st.header("📊 Attendance Dashboard")

    data = load_attendance(
        student_name,
        roll_number,
    )

    if data.empty:
        st.info(
            "No attendance recorded yet."
        )

    else:
        conducted = data[
            data.status != "Holiday"
        ]

        present = len(
            data[data.status == "Present"]
        )

        absent = len(
            data[data.status == "Absent"]
        )

        total = len(conducted)

        overall = (
            present / total * 100
            if total
            else 0
        )

        a, b, c = st.columns(3)

        a.metric(
            "Overall",
            f"{overall:.1f}%",
        )

        b.metric(
            "Present",
            present,
        )

        c.metric(
            "Absent",
            absent,
        )

        st.divider()

        timetable = load_timetable(
            student_id
        )

        subjects = []

        for day_name in DAYS:
            for _, _, code, subj in timetable.get(
                day_name,
                [],
            ):
                label = f"{code} — {subj}"

                if label not in subjects:
                    subjects.append(label)

        for value in data.subject.dropna().unique():
            if value not in subjects:
                subjects.append(value)

        report = []

        for subject in subjects:
            d = data[
                data.subject == subject
            ]

            p = len(
                d[d.status == "Present"]
            )

            ab = len(
                d[d.status == "Absent"]
            )

            h = len(
                d[d.status == "Holiday"]
            )

            t = p + ab

            pct = (
                p / t * 100
                if t
                else 0
            )

            report.append(
                {
                    "Subject": subject,
                    "Present": p,
                    "Absent": ab,
                    "Holiday": h,
                    "Total": t,
                    "Attendance %": round(
                        pct,
                        1,
                    ),
                    "Need for 75%": needed_for_75(
                        p,
                        t,
                    ),
                    "Can Miss": can_miss_at_75(
                        p,
                        t,
                    ),
                }
            )

        st.subheader(
            "📚 Subject-wise Attendance"
        )

        report_df = pd.DataFrame(
            report
        )

        st.dataframe(
            report_df,
            width="stretch",
            hide_index=True,
        )

        st.subheader(
            "🎯 75% Attendance Planner"
        )

        planner = []

        for row in report:
            if row["Total"] == 0:
                text = "No classes recorded"

            elif row["Attendance %"] < 75:
                text = (
                    f"Attend next "
                    f"{row['Need for 75%']} "
                    f"class(es) continuously"
                )

            else:
                text = (
                    f"You can miss "
                    f"{row['Can Miss']} "
                    f"class(es) and stay ≥ 75%"
                )

            planner.append(
                {
                    "Subject": row["Subject"],
                    "Current %": row["Attendance %"],
                    "Present": row["Present"],
                    "Total Conducted": row["Total"],
                    "Need to Reach 75%": row[
                        "Need for 75%"
                    ],
                    "Can Miss at 75%": row[
                        "Can Miss"
                    ],
                    "Status": text,
                }
            )

        st.dataframe(
            pd.DataFrame(planner),
            width="stretch",
            hide_index=True,
        )

        st.subheader(
            "⚠️ 75% Attendance Check"
        )

        any_low = False

        for row in report:
            if row["Total"] == 0:
                continue

            if row["Attendance %"] < 75:
                any_low = True

                st.error(
                    f"🔴 {row['Subject']}: "
                    f"{row['Attendance %']}% — "
                    f"attend the next "
                    f"{row['Need for 75%']} "
                    f"class(es) to reach 75%."
                )

            else:
                st.success(
                    f"🟢 {row['Subject']}: "
                    f"{row['Attendance %']}% — "
                    f"you can miss about "
                    f"{row['Can Miss']} "
                    f"class(es) and remain at "
                    f"or above 75%."
                )

        if not any_low:
            st.success(
                "🎉 All subjects with recorded "
                "classes are currently at or above 75%."
            )


# =====================================================
# HISTORY
# =====================================================

with history_tab:
    st.header(
        "📅 Attendance History"
    )

    data = load_attendance(
        student_name,
        roll_number,
    )

    if data.empty:
        st.info(
            "No attendance history yet."
        )

    else:
        history = data.copy()

        history["attendance_date"] = (
            pd.to_datetime(
                history["attendance_date"]
            ).dt.strftime(
                "%d-%m-%Y"
            )
        )

        history.columns = [
            "Date",
            "Subject",
            "Status",
        ]

        st.dataframe(
            history,
            width="stretch",
            hide_index=True,
        )

        st.download_button(
            "⬇️ Download Attendance CSV",
            history.to_csv(
                index=False
            ).encode("utf-8"),
            "attendance.csv",
            "text/csv",
            width="stretch",
        )
