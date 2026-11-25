✈️ FlyGo — Flight Booking Web App

FlyGo is a full-stack flight booking web application built with Flask, SQLAlchemy, MySQL, and HTML/CSS/JavaScript.
It includes secure authentication, OTP-based password reset, flight booking, admin tools, and PDF invoice generation.

🚀 Features

🔐 User Authentication (Register, Login, Password Hashing)

✉️ OTP Email Verification for password reset

✈️ Flight Booking System with passenger info and seat updates

📄 PDF Invoice Generation

🛠️ Admin Panel (users, bookings, refunds, blogs)

🔌 API-Based Backend (OTP, booking, admin actions)

🗂️ Project Structure
FlyGo/
├── static/        # CSS, JS, Images
├── templates/     # HTML templates
├── uploads/       # Admin image uploads
├──FlyGo_DB.sql
├── flight_routes.py
├── main.py
└── README.md

🛠️ Tech Stack

Frontend: HTML5, CSS3, JavaScript, Jinja2
Backend: Flask, SQLAlchemy, Flask-Mail
Database: MySQL
Security: Password hashing, validation, sessions, safe file uploads

🔌 Key API Endpoints
Method	Endpoint	Purpose
POST	/send_otp	Send OTP email
POST	/api/book-flight	Create flight booking
GET	/api/invoice/<id>	Download invoice PDF
GET	/api/admin/all-users	Admin users list
GET	/api/admin/all-bookings	Admin bookings list
▶️ How to Run FlyGo (With Database Setup)
1️⃣ Install Requirements
pip install -r requirements.txt

2️⃣ Create MySQL Database (flask_db)

Open MySQL and run:

CREATE DATABASE flask_db;


(Optional user creation)

CREATE USER 'flygo_user'@'localhost' IDENTIFIED BY 'yourpassword';
GRANT ALL PRIVILEGES ON flask_db.* TO 'flygo_user'@'localhost';
FLUSH PRIVILEGES;

3️⃣ Configure Database Connection

In main.py, update your SQLAlchemy URI:

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://flygo_user:yourpassword@localhost/flask_db'

4️⃣ Configure Email for OTP (credentials.json)
{
  "MAIL_SERVER": "smtp.gmail.com",
  "MAIL_PORT": 587,
  "MAIL_USERNAME": "your_email@gmail.com",
  "MAIL_PASSWORD": "your_app_password"
}


⚠️ Gmail requires an App Password, not your regular Gmail password.

5️⃣ Run the App
python main.py


Open in browser:

http://127.0.0.1:5000/


Tables will be auto-created on first run using SQLAlchemy.