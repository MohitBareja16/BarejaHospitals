import os
from dotenv import load_dotenv

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from models import (
    db,
    User,
    Doctor,
    Patient,
    Admin,
    Department,
    Appointment,
    DoctorAvailability,
    Treatment,
)

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///hospital.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
app.config["DEBUG"] = os.environ.get("FLASK_DEBUG", "False") == "True"

db.init_app(app)

# Authentication setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def LoadUser(user_id):
    return db.session.get(User, int(user_id))


# LOGIN ROUTES


@app.route("/", endpoint="home")
def Home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"], endpoint="login")
def Login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        current_account = User.query.filter_by(username=username).first()

        if current_account and check_password_hash(current_account.password, password):
            login_user(current_account)
            flash("Login Successful!", "success")

            if current_account.role == "admin":
                return redirect(url_for("admin_dashboard"))
            elif current_account.role == "doctor":
                return redirect(url_for("doctor_dashboard"))
            else:
                return redirect(url_for("patient_dashboard"))
        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"], endpoint="register")
def Register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")

        if User.query.filter_by(username=username).first():
            flash("Username already exists", "warning")
            return redirect(url_for("register"))

        hashed_pw = generate_password_hash(password, method="pbkdf2:sha256")
        new_user = User(username=username, password=hashed_pw, role=role)
        db.session.add(new_user)
        db.session.commit()

        if role == "patient":
            new_profile = Patient(user_id=new_user.id, full_name=username)
            db.session.add(new_profile)
        elif role == "doctor":
            pass
        elif role == "admin":
            new_profile = Admin(user_id=new_user.id, full_name=username)
            db.session.add(new_profile)

        db.session.commit()

        flash("Registration Successful! Please Login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout", endpoint="logout")
@login_required
def Logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ADMIN ROUTES


@app.route("/admin_dashboard", endpoint="admin_dashboard")
@login_required
def AdminDashboard():
    if current_user.role != "admin":
        flash("Access denied.", "danger")
        return redirect(url_for("login"))

    doctors = Doctor.query.all()
    patients = Patient.query.all()
    departments = Department.query.all()

    all_appointments = Appointment.query.order_by(
        Appointment.date_scheduled.desc()
    ).all()

    counts = {
        "doctors": len(doctors),
        "patients": len(patients),
        "appointments": len(all_appointments),
    }

    dept_stats = {d.name: 0 for d in departments}
    all_appointments = Appointment.query.all()
    for appt in all_appointments:
        if appt.doctor and appt.doctor.department:
            name = appt.doctor.department.name
            if name in dept_stats:
                dept_stats[name] += 1

    labels = list(dept_stats.keys())
    values = list(dept_stats.values())

    return render_template(
        "admin_dashboard.html",
        doctors=doctors,
        patients=patients,
        departments=departments,
        all_appointments=all_appointments,
        chart_labels=labels,
        chart_values=values,
        counts=counts,
    )


@app.route("/add_department", methods=["POST"], endpoint="add_department")
@login_required
def AddDepartment():
    if current_user.role != "admin":
        return redirect(url_for("home"))

    name = request.form.get("name")
    if name:
        new_dept = Department(name=name)
        db.session.add(new_dept)
        db.session.commit()
        flash("Department added successfully!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/add_doctor", methods=["POST"], endpoint="add_doctor")
@login_required
def AddDoctor():
    if current_user.role != "admin":
        return redirect(url_for("home"))

    username = request.form.get("username")
    password = request.form.get("password")
    full_name = request.form.get("full_name")
    department_id = request.form.get("department_id")

    hashed_pw = generate_password_hash(password, method="pbkdf2:sha256")
    new_user = User(username=username, password=hashed_pw, role="doctor")
    db.session.add(new_user)
    db.session.commit()

    new_doctor = Doctor(
        user_id=new_user.id, full_name=full_name, department_id=department_id
    )
    db.session.add(new_doctor)
    db.session.commit()

    flash("New Doctor registered successfully!", "success")
    return redirect(url_for("admin_dashboard"))


# DOCTOR ROUTES


@app.route("/doctor_dashboard", endpoint="doctor_dashboard")
@login_required
def DoctorDashboard():
    if current_user.role != "doctor":
        flash("Access denied. Doctors only.", "danger")
        return redirect(url_for("login"))

    doctor = current_user.doctor_profile

    appointments = (
        Appointment.query.filter_by(doctor_id=doctor.id)
        .order_by(Appointment.date_scheduled)
        .all()
    )
    availabilities = DoctorAvailability.query.filter_by(doctor_id=doctor.id).all()

    patient_ids = set(a.patient_id for a in appointments)
    my_patients = Patient.query.filter(Patient.id.in_(patient_ids)).all()

    return render_template(
        "doctor_dashboard.html",
        appointments=appointments,
        availabilities=availabilities,
        my_patients=my_patients,
    )


@app.route(
    "/add_treatment/<int:appointment_id>", methods=["POST"], endpoint="add_treatment"
)
@login_required
def AddTreatment(appointment_id):
    if current_user.role != "doctor":
        return redirect(url_for("home"))

    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.doctor_id != current_user.doctor_profile.id:
        flash("Unauthorized access to this appointment.", "danger")
        return redirect(url_for("doctor_dashboard"))

    diagnosis = request.form.get("diagnosis")
    prescription = request.form.get("prescription")
    notes = request.form.get("notes")
    visit_type = request.form.get("visit_type")
    tests_done = request.form.get("tests_done")

    new_treatment = Treatment(
        appointment_id=appointment_id,
        diagnosis=diagnosis,
        prescription=prescription,
        notes=notes,
        visit_type=visit_type,
        tests_done=tests_done,
    )

    appointment = Appointment.query.get(appointment_id)
    appointment.status = "Completed"

    db.session.add(new_treatment)
    db.session.commit()

    flash("Treatment details saved successfully!", "success")
    return redirect(url_for("doctor_dashboard"))


@app.route("/doctor_cancel_appointment/<int:id>", endpoint="doctor_cancel_appointment")
@login_required
def DoctorCancelAppointment(id):
    appt = Appointment.query.get_or_404(id)

    if appt.doctor_id != current_user.doctor_profile.id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("doctor_dashboard"))

    appt.status = "Cancelled"
    db.session.commit()

    flash("Appointment marked as Cancelled.", "warning")
    return redirect(url_for("doctor_dashboard"))


@app.route("/add_availability", methods=["POST"], endpoint="add_availability")
@login_required
def AddAvailability():
    if current_user.role != "doctor":
        return redirect(url_for("home"))

    day = request.form.get("day")
    start_str = request.form.get("start_time")
    end_str = request.form.get("end_time")

    start_time = datetime.strptime(start_str, "%H:%M").time()
    end_time = datetime.strptime(end_str, "%H:%M").time()

    new_slot = DoctorAvailability(
        doctor_id=current_user.doctor_profile.id,
        day_of_week=day,
        start_time=start_time,
        end_time=end_time,
    )

    db.session.add(new_slot)
    db.session.commit()

    flash("Availability slot added!", "success")
    return redirect(url_for("doctor_dashboard"))


# PATIENT ROUTES


@app.route("/patient_dashboard", endpoint="patient_dashboard")
@login_required
def PatientDashboard():
    if current_user.role != "patient":
        return redirect(url_for("home"))

    departments = Department.query.all()

    patient_id = current_user.patient_profile.id
    my_appointments = (
        Appointment.query.filter_by(patient_id=patient_id)
        .order_by(Appointment.date_scheduled.desc())
        .all()
    )

    return render_template(
        "patient_dashboard.html", departments=departments, appointments=my_appointments
    )


@app.route("/department/<int:dept_id>", endpoint="view_department")
@login_required
def ViewDepartment(dept_id):
    medical_unit = Department.query.get_or_404(dept_id)
    return render_template("department_view.html", dept=medical_unit)


@app.route(
    "/book/<int:doctor_id>", methods=["GET", "POST"], endpoint="book_appointment"
)
@login_required
def BookAppointment(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)

    weekly_schedule = DoctorAvailability.query.filter_by(doctor_id=doctor_id).all()

    existing_appointments = Appointment.query.filter_by(doctor_id=doctor_id).all()

    booked_slots = set()
    for appt in existing_appointments:
        booked_key = f"{appt.date_scheduled} {appt.time_scheduled}"
        booked_slots.add(booked_key)

    available_slots = []
    today = datetime.now().date()

    schedule_map = {}
    for slot in weekly_schedule:
        if slot.day_of_week not in schedule_map:
            schedule_map[slot.day_of_week] = []
        schedule_map[slot.day_of_week].append(slot)

    for i in range(7):
        current_day = today + timedelta(days=i)
        day_name = current_day.strftime("%A")
        date_str = current_day.strftime("%Y-%m-%d")

        if day_name in schedule_map:
            for slot in schedule_map[day_name]:

                slot_key = f"{date_str} {slot.start_time}"

                is_taken = slot_key in booked_slots

                available_slots.append(
                    {
                        "date_obj": current_day,
                        "date_str": date_str,
                        "day_name": day_name,
                        "start": slot.start_time,
                        "end": slot.end_time,
                        "is_taken": is_taken,
                    }
                )

    if request.method == "POST":
        date_str = request.form.get("date")
        time_str = request.form.get("time")

        existing = Appointment.query.filter_by(
            doctor_id=doctor_id,
            date_scheduled=datetime.strptime(date_str, "%Y-%m-%d").date(),
            time_scheduled=datetime.strptime(time_str, "%H:%M:%S").time(),
        ).first()
        if existing:
            flash("Error: This slot was just booked by someone else.", "danger")
            return redirect(url_for("book_appointment", doctor_id=doctor_id))

        scheduled_visit = Appointment(
            patient_id=current_user.patient_profile.id,
            doctor_id=doctor_id,
            date_scheduled=datetime.strptime(date_str, "%Y-%m-%d").date(),
            time_scheduled=datetime.strptime(time_str, "%H:%M:%S").time(),
            status="Scheduled",
        )
        db.session.add(scheduled_visit)
        db.session.commit()
        flash("Appointment Booked Successfully!", "success")
        return redirect(url_for("patient_dashboard"))

    return render_template("booking.html", doctor=doctor, slots=available_slots)


@app.route("/api/departments", methods=["GET"], endpoint="api_get_departments")
def ApiGetDepartments():
    depts = Department.query.all()
    data = [{"id": d.id, "name": d.name} for d in depts]
    return jsonify(data)


@app.route("/api/department", methods=["POST"], endpoint="api_create_dept")
def ApiCreateDepartment():
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Name is required"}), 400

    new_dept = Department(name=data["name"])
    db.session.add(new_dept)
    db.session.commit()
    return jsonify({"message": "Department created", "id": new_dept.id}), 201


@app.route("/api/department/<int:id>", methods=["PUT"], endpoint="api_update_dept")
def ApiUpdateDepartment(id):
    medical_unit = Department.query.get_or_404(id)
    data = request.get_json()
    if "name" in data:
        medical_unit.name = data["name"]

    db.session.commit()
    return jsonify({"message": "Department updated successfully"})


@app.route("/api/department/<int:id>", methods=["DELETE"], endpoint="api_delete_dept")
def ApiDeleteDepartment(id):
    medical_unit = Department.query.get_or_404(id)
    db.session.delete(medical_unit)
    db.session.commit()
    return jsonify({"message": "Department deleted successfully"})


@app.route("/api/doctors", methods=["GET"], endpoint="api_get_doctors")
def ApiGetDoctors():
    docs = Doctor.query.all()
    data = []
    for d in docs:
        data.append(
            {
                "id": d.id,
                "name": d.full_name,
                "department": d.department.name if d.department else "None",
                "qualification": d.qualification,
            }
        )
    return jsonify(data)


# PROFILE MANAGEMENT


@app.route("/profile", methods=["GET", "POST"], endpoint="profile")
@login_required
def Profile():
    user_profile = None
    if current_user.role == "patient":
        user_profile = current_user.patient_profile
    elif current_user.role == "doctor":
        user_profile = current_user.doctor_profile
    elif current_user.role == "admin":
        user_profile = current_user.admin_profile

    if request.method == "POST":
        if current_user.role != "admin":
            user_profile.full_name = request.form.get("full_name")

            if current_user.role == "patient":
                user_profile.phone = request.form.get("phone")
                user_profile.address = request.form.get("address")
                user_profile.age = request.form.get("age")
            elif current_user.role == "doctor":
                user_profile.qualification = request.form.get("qualification")

            db.session.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("profile"))

    return render_template("profile.html", user=current_user, profile=user_profile)


@app.route("/cancel_appointment/<int:id>", endpoint="cancel_appointment")
@login_required
def CancelAppointment(id):
    appt = Appointment.query.get_or_404(id)
    if appt.patient_id != current_user.patient_profile.id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for("patient_dashboard"))

    if appt.status == "Scheduled":
        appt.status = "Cancelled"
        db.session.commit()
        flash("Appointment cancelled.", "info")
    else:
        flash("Cannot cancel a completed appointment.", "warning")

    return redirect(url_for("patient_dashboard"))


@app.route("/reschedule/<int:appt_id>", methods=["GET", "POST"], endpoint="reschedule")
@login_required
def RescheduleAppointment(appt_id):
    appt = Appointment.query.get_or_404(appt_id)

    if appt.patient_id != current_user.patient_profile.id:
        flash("You cannot reschedule this appointment.", "danger")
        return redirect(url_for("patient_dashboard"))

    doctor = appt.doctor

    weekly_schedule = DoctorAvailability.query.filter_by(doctor_id=doctor.id).all()
    existing_appointments = Appointment.query.filter_by(doctor_id=doctor.id).all()

    booked_slots = set()
    for a in existing_appointments:
        if a.id != appt.id:
            booked_key = f"{a.date_scheduled} {a.time_scheduled}"
            booked_slots.add(booked_key)

    available_slots = []
    today = datetime.now().date()

    schedule_map = {}
    for slot in weekly_schedule:
        if slot.day_of_week not in schedule_map:
            schedule_map[slot.day_of_week] = []
        schedule_map[slot.day_of_week].append(slot)

    for i in range(7):
        current_day = today + timedelta(days=i)
        day_name = current_day.strftime("%A")
        date_str = current_day.strftime("%Y-%m-%d")

        if day_name in schedule_map:
            for slot in schedule_map[day_name]:
                slot_key = f"{date_str} {slot.start_time}"
                is_taken = slot_key in booked_slots

                available_slots.append(
                    {
                        "date_obj": current_day,
                        "date_str": date_str,
                        "day_name": day_name,
                        "start": slot.start_time,
                        "end": slot.end_time,
                        "is_taken": is_taken,
                    }
                )

    if request.method == "POST":
        date_str = request.form.get("date")
        time_str = request.form.get("time")

        appt.date_scheduled = datetime.strptime(date_str, "%Y-%m-%d").date()
        appt.time_scheduled = datetime.strptime(time_str, "%H:%M:%S").time()
        appt.status = "Scheduled"

        db.session.commit()
        flash("Appointment Rescheduled Successfully!", "success")
        return redirect(url_for("patient_dashboard"))

    return render_template(
        "reschedule.html", appointment=appt, doctor=doctor, slots=available_slots
    )


def create_admin():
    """
    Creates a default Admin account if one doesn't exist.
    Credential: admin / 12345
    """
    with app.app_context():
        admin_user = User.query.filter_by(role="admin").first()
        if not admin_user:
            print("--- NO ADMIN FOUND. CREATING DEFAULT ADMIN... ---")

            hashed_pw = generate_password_hash("12345", method="pbkdf2:sha256")
            new_admin_user = User(username="admin", password=hashed_pw, role="admin")
            db.session.add(new_admin_user)
            db.session.commit()

            new_admin_profile = Admin(
                user_id=new_admin_user.id, full_name="Super Admin"
            )
            db.session.add(new_admin_profile)
            db.session.commit()

            print("--- ADMIN CREATED: Login with 'admin' / '12345' ---")
        else:
            print("--- Admin account already exists. ---")


# ADMIN MANAGEMENT ROUTES


@app.route("/edit_doctor/<int:id>", methods=["GET", "POST"], endpoint="edit_doctor")
@login_required
def EditDoctor(id):
    if current_user.role != "admin":
        return redirect(url_for("home"))

    doctor = Doctor.query.get_or_404(id)
    departments = Department.query.all()

    if request.method == "POST":
        doctor.full_name = request.form.get("full_name")
        dept_id = request.form.get("department_id")
        if dept_id:
            doctor.department_id = dept_id

        db.session.commit()
        flash("Doctor profile updated successfully!", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("edit_doctor.html", doctor=doctor, departments=departments)


@app.route("/delete_doctor/<int:id>", endpoint="delete_doctor")
@login_required
def DeleteDoctor(id):
    if current_user.role != "admin":
        return redirect(url_for("home"))

    doctor = Doctor.query.get_or_404(id)

    current_account = User.query.get(doctor.user_id)

    db.session.delete(doctor)
    db.session.delete(current_account)
    db.session.commit()

    flash("Doctor deleted successfully.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin_delete_appt/<int:id>", endpoint="admin_delete_appt")
@login_required
def AdminDeleteAppt(id):
    if current_user.role != "admin":
        return redirect(url_for("home"))

    appt = Appointment.query.get_or_404(id)
    db.session.delete(appt)
    db.session.commit()

    flash("Appointment record deleted.", "info")
    return redirect(url_for("admin_dashboard"))


# DOCTOR: VIEW PATIENT HISTORY


@app.route("/doctor_view_history/<int:patient_id>", endpoint="doctor_view_history")
@login_required
def DoctorViewHistory(patient_id):
    if current_user.role != "doctor":
        return redirect(url_for("home"))

    patient = Patient.query.get_or_404(patient_id)

    history = (
        Appointment.query.filter_by(patient_id=patient_id, status="Completed")
        .order_by(Appointment.date_scheduled.desc())
        .all()
    )

    return render_template(
        "patient_history_doctor.html", patient=patient, history=history
    )


@app.route("/admin_view_history/<int:patient_id>", endpoint="admin_view_history")
@login_required
def AdminViewHistory(patient_id):
    if current_user.role != "admin":
        return redirect(url_for("login"))

    patient = Patient.query.get_or_404(patient_id)
    history = (
        Appointment.query.filter_by(patient_id=patient_id, status="Completed")
        .order_by(Appointment.date_scheduled.desc())
        .all()
    )

    return render_template(
        "patient_history_doctor.html", patient=patient, history=history
    )


@app.route(
    "/edit_patient_admin/<int:id>",
    methods=["GET", "POST"],
    endpoint="edit_patient_admin",
)
@login_required
def EditPatientAdmin(id):
    if current_user.role != "admin":
        return redirect(url_for("home"))

    patient = Patient.query.get_or_404(id)

    if request.method == "POST":
        patient.full_name = request.form.get("full_name")
        patient.phone = request.form.get("phone")
        patient.address = request.form.get("address")
        patient.age = request.form.get("age")

        db.session.commit()
        flash("Patient details updated.", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("edit_patient_admin.html", patient=patient)


@app.route("/delete_patient/<int:id>", endpoint="delete_patient")
@login_required
def DeletePatient(id):
    if current_user.role != "admin":
        return redirect(url_for("home"))

    patient = Patient.query.get_or_404(id)
    current_account = User.query.get(patient.user_id)

    db.session.delete(patient)
    db.session.delete(current_account)
    db.session.commit()

    flash("Patient removed from system.", "warning")
    return redirect(url_for("admin_dashboard"))


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        create_admin()
    # Use configured debug flag (do not run production with debug=True).
    app.run(debug=app.config.get("DEBUG", False))
