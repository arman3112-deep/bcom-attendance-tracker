import streamlit as st
import sqlite3
import hashlib
from datetime import date
import pandas as pd

# ============================================================
# APP SETTINGS
# ============================================================

st.set_page_config(
    page_title="Attendance Tracker",
    page_icon="📚",
    layout="wide"
)

DB_FILE = "attendance.db"

# ============================================================
# DATABASE
# ============================================================

def get_db():
    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            roll_number TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            course TEXT NOT NULL,
            section TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_number TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            lecture_number INTEGER NOT NULL,
            subject TEXT NOT NULL,
            UNIQUE(
                roll_number,
                weekday,
                lecture_number
            )
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_number TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            lecture_number INTEGER NOT NULL,
            subject TEXT NOT NULL,
            status TEXT NOT NULL,
            UNIQUE(
                roll_number,
                attendance_date,
                lecture_number
            )
        )
    """)

    connection.commit()
    connection.close()


init_database()

# ============================================================
# PASSWORD
# ============================================================

def hash_password(password):
    return hashlib.sha256(
        password.encode("utf-8")
    ).hexdigest()


# ============================================================
# STUDENT FUNCTIONS
# ============================================================

def get_student(roll_number):

    connection = get_db()

    student = connection.execute(
        """
        SELECT *
        FROM students
        WHERE roll_number = ?
        """,
        (roll_number,)
    ).fetchone()

    connection.close()

    return student


def create_student(
    full_name,
    roll_number,
    password,
    course,
    section
):

    connection = get_db()

    try:

        connection.execute(
            """
            INSERT INTO students
            (
                full_name,
                roll_number,
                password_hash,
                course,
                section
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                full_name.strip(),
                roll_number.strip(),
                hash_password(password),
                course.strip(),
                section.strip()
            )
        )

        connection.commit()

        return True

    except sqlite3.IntegrityError:

        return False

    finally:

        connection.close()


# ============================================================
# TIMETABLE
# ============================================================

def save_timetable(roll_number, timetable):

    connection = get_db()

    connection.execute(
        """
        DELETE FROM timetable
        WHERE roll_number = ?
        """,
        (roll_number,)
    )

    for item in timetable:

        if item["subject"].strip():

            connection.execute(
                """
                INSERT INTO timetable
                (
                    roll_number,
                    weekday,
                    lecture_number,
                    subject
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    roll_number,
                    item["weekday"],
                    item["lecture_number"],
                    item["subject"].strip()
                )
            )

    connection.commit()
    connection.close()


def get_timetable(roll_number):

    connection = get_db()

    rows = connection.execute(
        """
        SELECT
            weekday,
            lecture_number,
            subject
        FROM timetable
        WHERE roll_number = ?
        ORDER BY weekday, lecture_number
        """,
        (roll_number,)
    ).fetchall()

    connection.close()

    return [dict(row) for row in rows]


def get_classes_for_date(
    roll_number,
    selected_date
):

    weekday = selected_date.weekday()

    timetable = get_timetable(roll_number)

    return [
        item
        for item in timetable
        if item["weekday"] == weekday
    ]


# ============================================================
# ATTENDANCE
# ============================================================

def save_attendance(
    roll_number,
    selected_date,
    records
):

    # NEVER allow future dates
    if selected_date > date.today():

        return False

    connection = get_db()

    for record in records:

        connection.execute(
            """
            INSERT INTO attendance
            (
                roll_number,
                attendance_date,
                lecture_number,
                subject,
                status
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(
                roll_number,
                attendance_date,
                lecture_number
            )

            DO UPDATE SET
                subject = excluded.subject,
                status = excluded.status
            """,
            (
                roll_number,
                selected_date.isoformat(),
                record["lecture_number"],
                record["subject"],
                record["status"]
            )
        )

    connection.commit()
    connection.close()

    return True


def get_attendance(roll_number):

    connection = get_db()

    rows = connection.execute(
        """
        SELECT
            attendance_date,
            lecture_number,
            subject,
            status
        FROM attendance
        WHERE roll_number = ?
        ORDER BY
            attendance_date DESC,
            lecture_number
        """,
        (roll_number,)
    ).fetchall()

    connection.close()

    return pd.DataFrame(
        [dict(row) for row in rows]
    )


# ============================================================
# REPORT
# ============================================================

def make_report(data):

    if data.empty:

        return pd.DataFrame()

    subjects = sorted(
        data["subject"].unique()
    )

    report = []

    for subject in subjects:

        subject_data = data[
            data["subject"] == subject
        ]

        present = int(
            (
                subject_data["status"]
                == "Present"
            ).sum()
        )

        absent = int(
            (
                subject_data["status"]
                == "Absent"
            ).sum()
        )

        holiday = int(
            (
                subject_data["status"]
                == "Holiday"
            ).sum()
        )

        not_conducted = int(
            (
                subject_data["status"]
                == "Not Conducted"
            ).sum()
        )

        total = present + absent

        if total > 0:

            percentage = (
                present / total
            ) * 100

        else:

            percentage = 0

        report.append(
            {
                "Subject": subject,
                "Present": present,
                "Absent": absent,
                "Holiday": holiday,
                "Not Conducted": not_conducted,
                "Total": total,
                "Attendance %": round(
                    percentage,
                    1
                )
            }
        )

    return pd.DataFrame(report)


# ============================================================
# 75% CALCULATOR
# ============================================================

def classes_needed_for_75(
    present,
    total
):

    if total == 0:
        return 0

    if present / total >= 0.75:
        return 0

    needed = 0

    while (
        (present + needed)
        / (total + needed)
        < 0.75
    ):

        needed += 1

    return needed


# ============================================================
# SESSION
# ============================================================

if "logged_in" not in st.session_state:

    st.session_state.logged_in = False


if "roll_number" not in st.session_state:

    st.session_state.roll_number = ""


# ============================================================
# TITLE
# ============================================================

st.title("📚 Attendance Tracker")

st.caption(
    "Personal attendance tracker for any course, "
    "class and timetable."
)


# ============================================================
# LOGIN PAGE
# ============================================================

if not st.session_state.logged_in:

    login_tab, account_tab = st.tabs(
        [
            "🔐 Login",
            "📝 Create Account"
        ]
    )

    # --------------------------------------------------------
    # LOGIN
    # --------------------------------------------------------

    with login_tab:

        st.header("Login")

        roll_number = st.text_input(
            "Roll Number"
        )

        password = st.text_input(
            "Password",
            type="password"
        )

        if st.button(
            "🔓 Login",
            type="primary",
            use_container_width=True
        ):

            student = get_student(
                roll_number.strip()
            )

            if (
                student
                and
                student["password_hash"]
                == hash_password(password)
            ):

                st.session_state.logged_in = True

                st.session_state.roll_number = (
                    student["roll_number"]
                )

                st.rerun()

            else:

                st.error(
                    "Invalid roll number or password."
                )

    # --------------------------------------------------------
    # CREATE ACCOUNT
    # --------------------------------------------------------

    with account_tab:

        st.header("Create Account")

        full_name = st.text_input(
            "Full Name"
        )

        new_roll = st.text_input(
            "Roll Number"
        )

        course = st.text_input(
            "Course / Class",
            placeholder="Example: B.Com"
        )

        section = st.text_input(
            "Section / Division",
            placeholder="Example: M-2"
        )

        new_password = st.text_input(
            "Create Password",
            type="password"
        )

        confirm_password = st.text_input(
            "Confirm Password",
            type="password"
        )

        if st.button(
            "📝 Create Account",
            type="primary",
            use_container_width=True
        ):

            if not full_name.strip():

                st.warning(
                    "Enter your full name."
                )

            elif not new_roll.strip():

                st.warning(
                    "Enter your roll number."
                )

            elif not course.strip():

                st.warning(
                    "Enter your course."
                )

            elif not section.strip():

                st.warning(
                    "Enter your section."
                )

            elif not new_password:

                st.warning(
                    "Create a password."
                )

            elif new_password != confirm_password:

                st.error(
                    "Passwords do not match."
                )

            else:

                created = create_student(
                    full_name,
                    new_roll,
                    new_password,
                    course,
                    section
                )

                if created:

                    st.success(
                        "Account created successfully. "
                        "Now login."
                    )

                else:

                    st.error(
                        "This roll number already exists."
                    )

    st.stop()


# ============================================================
# LOGGED-IN STUDENT
# ============================================================

student = get_student(
    st.session_state.roll_number
)

if student is None:

    st.session_state.logged_in = False

    st.rerun()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.subheader("👤 My Account")

    st.write(
        f"**Name:** {student['full_name']}"
    )

    st.write(
        f"**Roll:** {student['roll_number']}"
    )

    st.write(
        f"**Course:** {student['course']}"
    )

    st.write(
        f"**Section:** {student['section']}"
    )

    if st.button(
        "🚪 Logout",
        use_container_width=True
    ):

        st.session_state.logged_in = False

        st.session_state.roll_number = ""

        st.rerun()


# ============================================================
# MAIN TABS
# ============================================================

today_tab, timetable_tab, report_tab, history_tab = st.tabs(
    [
        "📅 Today",
        "🗓️ My Timetable",
        "📊 Reports",
        "📜 Past Dates"
    ]
)


# ============================================================
# TODAY
# ============================================================

with today_tab:

    today = date.today()

    st.header(
        f"📅 {today.strftime('%A, %d %B %Y')}"
    )

    classes = get_classes_for_date(
        student["roll_number"],
        today
    )

    if not classes:

        st.info(
            "No lectures are scheduled for today."
        )

        st.write(
            "Go to **My Timetable** and add today's subjects."
        )

    else:

        st.subheader(
            f"{len(classes)} lecture(s) today"
        )

        records = []

        status_options = [
            "Present",
            "Absent",
            "Holiday",
            "Not Conducted"
        ]

        for item in sorted(
            classes,
            key=lambda x: x["lecture_number"]
        ):

            status = st.selectbox(
                (
                    f"Lecture "
                    f"{item['lecture_number']} — "
                    f"{item['subject']}"
                ),
                status_options,
                key=f"today_{item['lecture_number']}"
            )

            records.append(
                {
                    "lecture_number":
                        item["lecture_number"],
                    "subject":
                        item["subject"],
                    "status":
                        status
                }
            )

        if st.button(
            "💾 Save Today's Attendance",
            type="primary",
            use_container_width=True
        ):

            save_attendance(
                student["roll_number"],
                today,
                records
            )

            st.success(
                "Today's attendance saved."
            )

            st.rerun()


# ============================================================
# TIMETABLE
# ============================================================

with timetable_tab:

    st.header("🗓️ My Weekly Timetable")

    st.info(
        "You can have a different number of lectures "
        "on different days. There is no automatic "
        "IKS-HDA Wednesday/Thursday rule."
    )

    existing = get_timetable(
        student["roll_number"]
    )

    timetable_rows = []

    day_names = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday"
    ]

    for weekday in range(6):

        st.subheader(
            day_names[weekday]
        )

        existing_day = [
            x
            for x in existing
            if x["weekday"] == weekday
        ]

        existing_count = len(existing_day)

        lecture_count = st.number_input(
            f"Number of lectures on {day_names[weekday]}",
            min_value=0,
            max_value=10,
            value=max(existing_count, 4),
            step=1,
            key=f"count_{weekday}"
        )

        for lecture_number in range(
            1,
            lecture_count + 1
        ):

            old_subject = ""

            for old in existing_day:

                if (
                    old["lecture_number"]
                    == lecture_number
                ):

                    old_subject = old["subject"]

            subject = st.text_input(
                f"Lecture {lecture_number}",
                value=old_subject,
                key=f"subject_{weekday}_{lecture_number}"
            )

            if subject.strip():

                timetable_rows.append(
                    {
                        "weekday": weekday,
                        "lecture_number":
                            lecture_number,
                        "subject": subject
                    }
                )

    if st.button(
        "💾 Save My Timetable",
        type="primary",
        use_container_width=True
    ):

        save_timetable(
            student["roll_number"],
            timetable_rows
        )

        st.success(
            "Your timetable has been saved."
        )

        st.rerun()


# ============================================================
# REPORT
# ============================================================

with report_tab:

    st.header("📊 Attendance Report")

    attendance = get_attendance(
        student["roll_number"]
    )

    if attendance.empty:

        st.info(
            "No attendance has been recorded yet."
        )

    else:

        report = make_report(
            attendance
        )

        total_present = int(
            (
                attendance["status"]
                == "Present"
            ).sum()
        )

        total_absent = int(
            (
                attendance["status"]
                == "Absent"
            ).sum()
        )

        total_classes = (
            total_present
            + total_absent
        )

        if total_classes > 0:

            overall = round(
                total_present
                / total_classes
                * 100,
                1
            )

        else:

            overall = 0

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Overall",
            f"{overall}%"
        )

        col2.metric(
            "Present",
            total_present
        )

        col3.metric(
            "Absent",
            total_absent
        )

        st.subheader(
            "📚 Subject-wise Attendance"
        )

        st.dataframe(
            report,
            use_container_width=True,
            hide_index=True
        )

        # ----------------------------------------------------
        # 75%
        # ----------------------------------------------------

        st.subheader(
            "⚠️ 75% A
