from flask import Flask, Response,render_template, request, redirect, url_for, session
import json,csv
import os
from datetime import date
from werkzeug.utils import secure_filename
from io import BytesIO,StringIO



app = Flask(__name__)
app.secret_key = "super_secret_key_change_later"

# ---------- FILE PATHS ----------
DATA_FOLDER = "data"
STUDENTS_FILE = os.path.join(DATA_FOLDER, "students.json")
ATTENDANCE_FILE = os.path.join(DATA_FOLDER, "attendance.json")
USERS_FILE = os.path.join(DATA_FOLDER, "users.json")
DEPARTMENTS_FILE = os.path.join(DATA_FOLDER, "departments.json")

os.makedirs(DATA_FOLDER, exist_ok=True)

# ---------- HELPERS ----------
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

@app.route("/export_csv")
def export_csv():
    attendance = load_json(ATTENDANCE_FILE, {})

    rows = [["Date", "Roll", "Name", "Status"]]

    for day, records in attendance.items():
        for r in records:
            rows.append([day, r["roll"], r["name"], r["status"]])

    def generate():
        for row in rows:
            yield ",".join(row) + "\n"

    return Response(generate(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=attendance.csv"})

# ---------- ROOT → LOGIN ----------
@app.route("/", methods=["GET","POST"])
@app.route("/login", methods=["GET","POST"])
def login():

    users = load_json(USERS_FILE, [])

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        for user in users:
            if user["username"] == username and user["password"] == password:
                session["username"] = username
                return redirect(url_for("dashboard"))

    return render_template("login.html")

@app.route("/signup", methods=["GET","POST"])
def signup():

    users = load_json(USERS_FILE, [])

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        users.append({
            "username": username,
            "password": password
        })

        save_json(USERS_FILE, users)

        return redirect(url_for("login"))

    return render_template("signup.html")

# ---------- DASHBOARD ----------
@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))

    students = load_json(STUDENTS_FILE, [])
    attendance = load_json(ATTENDANCE_FILE, {})

    # Count UNIQUE students by dept (fix: use roll+dept as unique key)
    seen_rolls = set()
    dept_students = {}

    for student in students:
        roll = student.get("roll")
        dept_sem = student.get("dept_sem", "Unknown")
        dept = dept_sem.split("-")[0] if "-" in dept_sem else dept_sem

        unique_key = f"{roll}-{dept}"  # FIX: combine roll + dept

        if unique_key not in seen_rolls:
            seen_rolls.add(unique_key)
            if dept not in dept_students:
                dept_students[dept] = 0
            dept_students[dept] += 1

    total_students = sum(dept_students.values())  # Total unique students
    total_days = len(attendance)

    # Present today
    today = date.today().isoformat()
    today_records = attendance.get(today, [])
    present_today = len([r for r in today_records if r["status"] == "Present"])

    # At-risk students (below 75% attendance)
    at_risk_dict = {}
    for day_records in attendance.values():
        for record in day_records:
            roll = record.get("roll")
            if roll not in at_risk_dict:
                at_risk_dict[roll] = {"present": 0, "total": 0, "name": record.get("name", "")}
            at_risk_dict[roll]["total"] += 1
            if record.get("status") == "Present":
                at_risk_dict[roll]["present"] += 1

    at_risk_students = []
    for roll, data in at_risk_dict.items():
        if data["total"] > 0:
            percentage = (data["present"] / data["total"]) * 100
            if percentage < 75:
                at_risk_students.append({
                    "roll": roll,
                    "name": data["name"],
                    "percentage": round(percentage, 1)
                })
    # Calendar data - mark days with attendance
    import calendar
    from datetime import datetime
    
    current_month = datetime.now().month
    current_year = datetime.now().year
    
    # Get all dates when attendance was marked
    marked_days = set()
    low_attendance_days = set()
    
    for date_str in attendance.keys():
        try:
            date_obj = datetime.fromisoformat(date_str)
            if date_obj.month == current_month and date_obj.year == current_year:
                marked_days.add(date_obj.day)
        except:
            pass
    
    # Get calendar for current month
    cal = calendar.monthcalendar(current_year, current_month)
    month_name = calendar.month_name[current_month]

    return render_template(
        "dashboard.html",
        total_students=total_students,
        dept_students=dept_students,
        total_days=total_days,
        present_today=present_today,
        at_risk_count=len(at_risk_students),
        at_risk_students=at_risk_students,
        today=date.today(),
        calendar_data=cal,
        month_name=month_name,
        current_year=current_year,
        marked_days=marked_days
    )
@app.route("/bulk_import_students", methods=["POST"])
def bulk_import_students():
    if "username" not in session:
        return redirect(url_for("login"))
    
    if "file" not in request.files:
        return "No file uploaded", 400
    
    file = request.files["file"]
    if file.filename == "":
        return "No file selected", 400
    
    students = load_json(STUDENTS_FILE, [])
    
    try:
        stream = file.stream.read().decode("UTF8").splitlines()
        reader = csv.DictReader(stream)
        
        for row in reader:
            students.append({
                "roll": row.get("roll"),
                "name": row.get("name"),
                "department": row.get("department"),
                "semester": row.get("semester"),
                "subject": row.get("subject")
            })
        
        save_json(STUDENTS_FILE, students)
        return redirect(url_for("students"))
    except Exception as e:
        return f"Error: {str(e)}", 400


# ---------- STUDENTS ----------
@app.route("/students", methods=["GET", "POST"])
def students():

    students = load_json(STUDENTS_FILE, [])
    departments = load_json("data/departments.json", [])

    search_query = request.args.get("search", "").lower()

    # SEARCH FILTER
    if search_query:
        students = [
            s for s in students
            if search_query in s["name"].lower() or search_query in s["roll"]
        ]

    # ADD STUDENT
    if request.method == "POST":

        roll = request.form["roll"]
        name = request.form["name"]
        dept_sem = request.form["department_semester"]
        subject = request.form["subject"]

        # Prevent duplicate roll numbers
        for s in students:
            if s["roll"] == roll and s["subject"] == subject:
                return redirect(url_for("students"))

        students.append({
            "roll": roll,
            "name": name,
            "dept_sem": dept_sem,
            "subject": subject
        })
        students = sorted(students, key=lambda x: int(x["roll"]))

        save_json(STUDENTS_FILE, students)

        return redirect(url_for("students"))

    # GROUP STUDENTS BY DEPARTMENT + SUBJECT
    grouped = {}

    for s in students:

        key = s["dept_sem"] + "|" + s["subject"]

        if key not in grouped:
            grouped[key] = []

        grouped[key].append(s)

    return render_template(
        "students.html",
        students=students,
        departments=departments,
        grouped_students=grouped
    )

@app.route("/copy_students", methods=["POST"])
def copy_students():

    students = load_json(STUDENTS_FILE, [])

    # safely get values from form
    source_subject = request.form.get("source_subject")
    target_subject = request.form.get("target_subject")

    # if form values missing, just go back
    if not source_subject or not target_subject:
        return redirect(url_for("students"))

    new_students = []

    for s in students:

        if s["subject"].lower() == source_subject.lower():

            # check if student already exists in target subject
            exists = any(
                x["roll"] == s["roll"] and x["subject"].lower() == target_subject.lower()
                for x in students
            )

            if not exists:
                new_students.append({
                    "roll": s["roll"],
                    "name": s["name"],
                    "dept_sem": s["dept_sem"],
                    "subject": target_subject
                })

    students.extend(new_students)

    # keep roll numbers sorted
    students = sorted(students, key=lambda x: int(x["roll"]))

    save_json(STUDENTS_FILE, students)

    return redirect(url_for("students"))

@app.route("/delete_student/<roll>/<subject>")
def delete_student(roll, subject):

    students = load_json(STUDENTS_FILE, [])

    students = [
        s for s in students
        if not (s["roll"] == roll and s["subject"] == subject)
    ]

    save_json(STUDENTS_FILE, students)

    return redirect(url_for("students"))


@app.route("/add_department", methods=["POST"])
def add_department():

    department = request.form["department"]
    semester = request.form["semester"]

    with open("data/departments.json") as f:
        departments = json.load(f)

    departments.append({
        "department": department,
        "semester": semester
    })

    with open("data/departments.json","w") as f:
        json.dump(departments,f)

    return redirect(url_for("students"))


# ---------- MARK ATTENDANCE ----------


@app.route("/mark_attendance", methods=["GET", "POST"])
def mark_attendance():
    students = load_json(STUDENTS_FILE, [])
    attendance = load_json(ATTENDANCE_FILE, {})
    departments = load_json(DEPARTMENTS_FILE, [])  # [{"department":"CSE","semester":"1"}, ...]

    # Group students by dept_sem + subject
    grouped_students = {}
    for s in students:
        key = f"{s['dept_sem']}|{s['subject']}"
        grouped_students.setdefault(key, []).append(s)

    # Get selected department and subject from query parameters
    selected_dept = request.args.get("dept")  # e.g., "CSE-1"
    selected_subject = request.args.get("subject")  # e.g., "dbms"

    # Determine subjects for the selected department
    dept_subjects = []
    if selected_dept:
        for key in grouped_students.keys():
            if key.startswith(selected_dept + "|"):
                subj = key.split("|")[1]
                if subj not in dept_subjects:
                    dept_subjects.append(subj)

    # Handle POST (saving attendance)
    if request.method == "POST" and selected_dept and selected_subject:
        today = date.today().isoformat()
        if today not in attendance or not isinstance(attendance[today], list):
            attendance[today] = []

        key = f"{selected_dept}|{selected_subject}"
        for s in grouped_students.get(key, []):
            # Avoid duplicate entries
            exists = [r for r in attendance[today] if r["roll"] == s["roll"] and r["subject"] == selected_subject]
            if exists:
                continue

            status = "Present" if request.form.get(f"present_{s['roll']}") else "Absent"
            attendance[today].append({
                "roll": s["roll"],
                "name": s["name"],
                "status": status,
                "dept_sem": selected_dept,
                "subject": selected_subject
            })

        save_json(ATTENDANCE_FILE, attendance)
        return redirect(url_for("view_attendance",dept=selected_dept,subject=selected_subject))

    return render_template(
        "mark_attendance.html",
        departments=departments,
        grouped_students=grouped_students,
        selected_dept=selected_dept,
        selected_subject=selected_subject,
        dept_subjects=dept_subjects
    )
# ---------- VIEW ATTENDANCE ----------
@app.route("/view-attendance", methods=["GET"])
def view_attendance():
    students = load_json(STUDENTS_FILE, [])
    attendance = load_json(ATTENDANCE_FILE, {})
    departments = load_json(DEPARTMENTS_FILE, [])

    # Selected department & subject
    selected_dept = request.args.get("dept")  # e.g., "CSE-1"
    selected_subject = request.args.get("subject")  # e.g., "DBMS"

    # Group students by dept_sem|subject
    grouped_students = {}
    for s in students:
        key = f"{s['dept_sem']}|{s['subject']}"
        grouped_students.setdefault(key, []).append(s)

    # Determine subjects for the selected department
    dept_subjects = []
    if selected_dept:
        for key in grouped_students.keys():
            if key.startswith(selected_dept + "|"):
                subj = key.split("|")[1]
                if subj not in dept_subjects:
                    dept_subjects.append(subj)

    # Prepare student attendance summary ONLY if both dept & subject are selected
    student_attendance = {}
    if selected_dept and selected_subject:
        key = f"{selected_dept}|{selected_subject}"
        student_attendance[key] = {}
        for s in grouped_students.get(key, []):
            total_classes = 0
            present_count = 0
            for day_records in attendance.values():
                for r in day_records:
                    # check both dept_sem and subject match
                    if r.get("roll") == s["roll"] and r.get("dept_sem") == selected_dept and r.get("subject") == selected_subject:
                        total_classes += 1
                        if r.get("status") == "Present":
                            present_count += 1
            percentage = round((present_count / total_classes * 100) if total_classes > 0 else 0, 2)
            student_attendance[key][s["roll"]] = {
                "present": present_count,
                "total": total_classes,
                "percentage": percentage
            }

    return render_template(
        "view_attendance.html",
        departments=departments,
        selected_dept=selected_dept,
        selected_subject=selected_subject,
        dept_subjects=dept_subjects,
        grouped_students=grouped_students,
        student_attendance=student_attendance,
        attendance=attendance
    )

# ---------- NOTIFICATIONS ----------
@app.route("/notifications")
def notifications():
    if "username" not in session:
        return redirect(url_for("login"))

    students = load_json(STUDENTS_FILE, [])
    attendance = load_json(ATTENDANCE_FILE, {})

    at_risk = []

    for s in students:
        total = 0
        present = 0
        for day_records in attendance.values():
            for r in day_records:
                if r.get("roll") == s["roll"] and r.get("subject") == s["subject"]:
                    total += 1
                    if r.get("status") == "Present":
                        present += 1
        if total > 0:
            percentage = round((present / total) * 100, 2)
            if percentage < 75:
                at_risk.append({
                    "roll": s["roll"],
                    "name": s["name"],
                    "subject": s["subject"],
                    "dept_sem": s["dept_sem"],
                    "present": present,
                    "total": total,
                    "percentage": percentage
                })

    return render_template("notifications.html", at_risk=at_risk)


# ---------- DOWNLOAD REPORT ----------
@app.route("/download_report")
def download_report():
    if "username" not in session:
        return redirect(url_for("login"))

    students = load_json(STUDENTS_FILE, [])
    attendance = load_json(ATTENDANCE_FILE, {})

    rows = [["Roll", "Name", "Department", "Subject", "Present", "Total Classes", "Percentage"]]

    for s in students:
        total = 0
        present = 0
        for day_records in attendance.values():
            for r in day_records:
                if r.get("roll") == s["roll"] and r.get("subject") == s["subject"]:
                    total += 1
                    if r.get("status") == "Present":
                        present += 1
        percentage = round((present / total * 100), 2) if total > 0 else 0
        rows.append([
            s["roll"],
            s["name"],
            s["dept_sem"],
            s["subject"],
            str(present),
            str(total),
            f"{percentage}%"
        ])

    def generate():
        for row in rows:
            yield ",".join(row) + "\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=attendance_report.csv"}
    )

@app.route("/at_risk_students")
def at_risk_students():
    if "username" not in session:
        return redirect(url_for("login"))
    
    students = load_json(STUDENTS_FILE, [])
    attendance = load_json(ATTENDANCE_FILE, {})
    
    # Dictionary to store unique students (by roll number)
    at_risk_dict = {}
    
    for day_records in attendance.values():
        for record in day_records:
            roll = record.get("roll")
            
            # If student not yet in dict, add them
            if roll not in at_risk_dict:
                # Find student name
                for student in students:
                    if student["roll"] == roll:
                        at_risk_dict[roll] = {
                            "name": student["name"],
                            "roll": roll,
                            "present": 0,
                            "total": 0
                        }
                        break
            
            # Count attendance
            if roll in at_risk_dict:
                at_risk_dict[roll]["total"] += 1
                if record.get("status") == "Present":
                    at_risk_dict[roll]["present"] += 1
    
    # Filter only below 75%
    at_risk_list = []
    for roll, data in at_risk_dict.items():
        if data["total"] > 0:
            percentage = (data["present"] / data["total"]) * 100
            if percentage < 75:
                at_risk_list.append({
                    "name": data["name"],
                    "roll": roll,
                    "percentage": round(percentage, 1),
                    "present": data["present"],
                    "total": data["total"]
                })
    
    return render_template(
        "at_risk_students.html",
        at_risk_students=at_risk_list,
        total_students=len(students)
    )
@app.route("/download_csv_template")
def download_csv_template():
    csv_content = "roll,name,department,semester,subject\n101,Student Name,CSE,3,DBMS\n102,Another Student,CSE,3,Computer Network"
    
    return send_file(
        BytesIO(csv_content.encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="students_template.csv"
    )
# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- RUN ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)