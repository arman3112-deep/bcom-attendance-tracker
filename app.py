import streamlit as st
import sqlite3
import hashlib
import secrets
import math
from datetime import date
import pandas as pd


# =====================================================
# APP SETTINGS
# =====================================================

st.set_page_config(
    page_title="B.Com Attendance Tracker",
    page_icon="📚",
    layout="centered",
)


# =====================================================
# SUBJECTS
# =====================================================

SUBJECTS = {
    "SPB": "Structure and Process of Business",
    "FA": "Fundamentals of Accounting",
    "FEC": "Fundamentals of English and Communication",
    "BSC": "Basic Statistics for Commerce",
    "EET": "Elements of Economic Theory",
    "ESB": "Essential Skills for Banking",
    "IKS-HDA": "IKS - HDA",
}


# Wednesday and Thursday IKS-HDA is present in the timetable,
# but the lecture is NOT CONDUCTED and must not count.
AUTO_HOLIDAYS = {
    "Wednesday": {"IKS-HDA"},
    "Thursday": {"IKS-HDA"},
}


# =====================================================
# M-2 TIMETABLE - 4 LECTURES PER DAY
# =====================================================

TIMETABLE = {
    "Monday": [
        ("3:00–4:00 PM", "SPB"),
        ("4:00–5:00 PM", "FA"),
        ("5:00–6:00 PM", "BSC"),
        ("6:00–7:00 PM", "IKS-HDA"),
    ],
    "Tuesday": [
        ("3:00–4:00 PM", "SPB"),
        ("4:00–5:00 PM", "FA"),
        ("5:00–6:00 PM", "BSC"),
        ("6:00–7:00 PM", "IKS-HDA"),
    ],
    "Wednesday": [
        ("3:00–4:00 PM", "SPB"),
        ("4:00–5:00 PM", "FA"),
        ("5:00–6:00 PM", "EET"),
        ("6:00–7:00 PM", "IKS-HDA"),
    ],
    "Thursday": [
        ("3:00–4:00 PM", "SPB"),
        ("4:00–5:00 PM", "FA"),
        ("5:00–6:00 PM", "EET"),
        ("6:00–7:00 PM", "IKS-HDA"),
    ],
    "Friday": [
        ("3:00–4:00 PM", "FEC"),
        ("4:00–5:00 PM", "EET"),
        ("5:00–6:00 PM", "BSC"),
        ("6:00–7:00 PM", "ESB"),
    ],
    "Saturday": [
        ("3:00–4:00 PM", "FEC"),
        ("4:00–5:00 PM", "EET"),
        ("5:00–6:00 PM", "BSC"),
        ("6:00–7:00 PM", "ESB"),
    ],
}


# =====================================================
# PASSWORD FUNCTIONS
# =====================================================

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        200_000,
    )

    return salt.hex() + ":" + password_hash.hex()


def verify_password(password, stored_hash):
    try:
        salt_hex, hash_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)

        test_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            200_000,
        ).hex()

        return secrets.compare_digest(test_hash, hash_hex)
    except (ValueError, TypeError):
        return False


# =====================================================
# DATABASE
# =====================================================

def get_connection():
    connection = sqlite3.connect("attendance.db")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            roll_number TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(
                student_name,
                roll_number,
                attendance_date,
                subject
            )
        )
        """
    )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            roll_number TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )

    connection.commit()
    return connection


# Create database tables when the app starts.
connection = get_connection()
connection.close()


# =====================================================
# STUDENT ACCOUNT FUNCTIONS
# =====================================================

def register_student(full_name, roll_number, password):
    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO students (
                full_name,
                roll_number,
                password_hash
            )
            VALUES (?, ?, ?)
            """,
            (
                full_name,
                roll_number,
                hash_password(password),
            ),
        )
        connection.commit()
        return True, "Account created successfully."

    except sqlite3.IntegrityError:
        return False, "This roll number is already registered."

    finally:
        connection.close()


def login_student(roll_number, password):
    connection = get_connection()

    student = connection.execute(
        """
        SELECT id, full_name, roll_number, password_hash
        FROM students
        WHERE roll_number = ?
        """,
        (roll_number,),
    ).fetchone()

    connection.close()

    if student is None:
        return None

    if not verify_password(password, student[3]):
        return None

    return {
        "id": student[0],
        "full_name": student[1],
        "roll_number": student[2],
    }


# =====================================================
# ATTENDANCE FUNCTIONS
# =====================================================

def save_attendance(name, roll_number, selected_date, attendance_data):
    connection = get_connection()

    try:
        for subject, status in attendance_data.items():
            connection.execute(
                """
                INSERT INTO attendance (
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
                    roll_number,
                    selected_date.isoformat(),
                    subject,
                    status,
                ),
            )

        connection.commit()

    finally:
        connection.close()


def load_attendance(name, roll_number):
    connection = get_connection()

    data = pd.read_sql_query(
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
        connection,
        params=(name, roll_number),
    )

    connection.close()
    return data


# =====================================================
# SESSION STATE
# =====================================================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "student_id" not in st.session_state:
    st.session_state.student_id = None

if "student_name" not in st.session_state:
    st.session_state.student_name = ""

if "roll_number" not in st.session_state:
    st.session_state.roll_number = ""


# =====================================================
# LOGIN / REGISTRATION SCREEN
# =====================================================

if not st.session_state.logged_in:
    st.title("📚 B.Com Attendance Tracker")
    st.caption("F.Y. B.Com • M-2 • 2026–27")

    login_tab, register_tab = st.tabs(
        ["🔐 Login", "📝 Create Account"]
    )

    with login_tab:
        st.subheader("Login to your account")

        login_roll = st.text_input(
            "Roll Number",
            key="login_roll",
        )

        login_password = st.text_input(
            "Password",
            type="password",
            key="login_password",
        )

        if st.button(
            "🔐 Login",
            type="primary",
            width="stretch",
        ):
            login_roll = login_roll.strip()

            if not login_roll or not login_password:
                st.error("Please enter your roll number and password.")
            else:
                student = login_student(
                    login_roll,
                    login_password,
                )

                if student is None:
                    st.error("Invalid roll number or password.")
                else:
                    st.session_state.logged_in = True
                    st.session_state.student_id = student["id"]
                    st.session_state.student_name = student["full_name"]
                    st.session_state.roll_number = student["roll_number"]
                    st.success("Login successful!")
                    st.rerun()

    with register_tab:
        st.subheader("Create your student account")

        register_name = st.text_input(
            "Full Name",
            key="register_name",
        )

        register_roll = st.text_input(
            "Roll Number",
            key="register_roll",
        )

        register_password = st.text_input(
            "Create Password",
            type="password",
            key="register_password",
        )

        register_password_again = st.text_input(
            "Confirm Password",
            type="password",
            key="register_password_again",
        )

        st.caption(
            "Your roll number must be unique. "
            "Do not share your password with friends."
        )

        if st.button(
            "📝 Create Account",
            type="primary",
            width="stretch",
        ):
            register_name = register_name.strip()
            register_roll = register_roll.strip()

            if not register_name or not register_roll:
                st.error("Please enter your full name and roll number.")
            elif not register_password:
                st.error("Please create a password.")
            elif len(register_password) < 6:
                st.error("Password must be at least 6 characters.")
            elif register_password != register_password_again:
                st.error("Passwords do not match.")
            else:
                success, message = register_student(
                    register_name,
                    register_roll,
                    register_password,
                )

                if success:
                    st.success(
                        "Account created. Now open the Login tab "
                        "and login with your roll number and password."
                    )
                else:
                    st.error(message)

    st.stop()


# =====================================================
# LOGGED-IN PROFILE
# =====================================================

student_name = st.session_state.student_name
roll_number = st.session_state.roll_number

st.title("📚 B.Com Attendance Tracker")
st.caption("F.Y. B.Com • M-2 • 2026–27")

st.sidebar.header("👤 My Account")
st.sidebar.write(f"**Name:** {student_name}")
st.sidebar.write(f"**Roll No.:** {roll_number}")
st.sidebar.info(
    "Division: M-2\n\n"
    "Roll range: 121–240"
)

if st.sidebar.button("🚪 Logout", width="stretch"):
    st.session_state.logged_in = False
    st.session_state.student_id = None
    st.session_state.student_name = ""
    st.session_state.roll_number = ""
    st.rerun()


# =====================================================
# TABS
# =====================================================

tab1, tab2, tab3 = st.tabs(
    [
        "📝 Attendance",
        "📊 Dashboard",
        "📅 History",
    ]
)


# =====================================================
# ATTENDANCE TAB
# =====================================================

with tab1:
    st.header("📝 Mark Attendance")

    selected_date = st.date_input(
        "Select Date",
        value=date.today(),
    )

    day_name = selected_date.strftime("%A")

    st.subheader(
        f"📅 {day_name}, "
        f"{selected_date.strftime('%d %B %Y')}"
    )

    classes = TIMETABLE.get(day_name, [])

    if not classes:
        st.info("Sunday — No regular classes.")
    else:
        st.write("### Today's Classes")
        attendance_data = {}

        whole_day_holiday = st.checkbox(
            "🟡 College Holiday — mark entire day as holiday",
            key=f"whole_day_{selected_date}",
        )

        if whole_day_holiday:
            st.info(
                "This entire day will NOT be counted "
                "as attended or missed classes."
            )

        for index, (time, subject) in enumerate(classes):
            st.divider()
            st.markdown(f"### {time}")
            st.write(
                f"**{subject}** — "
                f"{SUBJECTS[subject]}"
            )

            # Wednesday and Thursday IKS-HDA is automatically not conducted.
            if subject in AUTO_HOLIDAYS.get(day_name, set()):
                attendance_data[subject] = "Holiday"
                st.warning(
                    "🟡 Not Conducted — IKS-HDA lecture is not conducted "
                    "on this day and will not count towards attendance."
                )

            elif whole_day_holiday:
                attendance_data[subject] = "Holiday"
                st.warning("🟡 College Holiday — not counted.")

            else:
                status = st.radio(
                    "Status",
                    ["Present", "Absent", "Holiday"],
                    horizontal=True,
                    key=f"status_{selected_date}_{index}_{subject}",
                )
                attendance_data[subject] = status

        st.divider()

        if st.button(
            "💾 Save Attendance",
            type="primary",
            width="stretch",
        ):
            save_attendance(
                student_name,
                roll_number,
                selected_date,
                attendance_data,
            )
            st.success("✅ Attendance saved successfully!")


# =====================================================
# DASHBOARD
# =====================================================

with tab2:
    st.header("📊 Attendance Dashboard")

    data = load_attendance(student_name, roll_number)

    if data.empty:
        st.info("No attendance recorded yet.")
    else:
        total_classes = len(data[data["status"] != "Holiday"])
        present_classes = len(data[data["status"] == "Present"])
        absent_classes = len(data[data["status"] == "Absent"])

        if total_classes > 0:
            overall_percentage = (
                present_classes / total_classes
            ) * 100
        else:
            overall_percentage = 0

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Overall",
            f"{overall_percentage:.1f}%",
        )
        col2.metric("Present", present_classes)
        col3.metric("Absent", absent_classes)

        st.divider()
        st.subheader("📚 Subject-wise Attendance")

        report = []

        for subject in SUBJECTS:
            subject_data = data[data["subject"] == subject]

            present = len(
                subject_data[subject_data["status"] == "Present"]
            )
            absent = len(
                subject_data[subject_data["status"] == "Absent"]
            )
            holiday = len(
                subject_data[subject_data["status"] == "Holiday"]
            )

            total = present + absent

            if total > 0:
                percentage = (present / total) * 100
            else:
                percentage = 0

            report.append(
                {
                    "Subject": subject,
                    "Present": present,
                    "Absent": absent,
                    "Holiday": holiday,
                    "Total": total,
                    "Attendance %": round(percentage, 1),
                }
            )

        report_df = pd.DataFrame(report)

        st.dataframe(
            report_df,
            width="stretch",
            hide_index=True,
        )

        st.subheader("⚠️ 75% Attendance Check")

        for row in report:
            subject = row["Subject"]
            present = row["Present"]
            total = row["Total"]
            percentage = row["Attendance %"]

            if total == 0:
                continue

            if percentage < 75:
                needed = max(
                    0,
                    math.ceil(
                        (0.75 * total - present) / 0.25
                    ),
                )

                st.error(
                    f"🔴 {subject}: {percentage}% — "
                    f"try to attend the next {needed} class(es) "
                    "to reach 75%."
                )
            else:
                can_miss = math.floor(
                    present / 0.75 - total
                )

                st.success(
                    f"🟢 {subject}: {percentage}% — "
                    f"you can currently miss about "
                    f"{max(0, can_miss)} class(es) "
                    "and remain at or above 75%."
                )


# =====================================================
# HISTORY
# =====================================================

with tab3:
    st.header("📅 Attendance History")

    data = load_attendance(student_name, roll_number)

    if data.empty:
        st.info("No attendance history yet.")
    else:
        history = data.copy()
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

        csv = history.to_csv(index=False).encode("utf-8")

        st.download_button(
            "⬇️ Download Attendance CSV",
            csv,
            file_name="attendance.csv",
            mime="text/csv",
            width="stretch",
        )
