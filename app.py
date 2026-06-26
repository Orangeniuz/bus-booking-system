from datetime import date, timedelta
import mysql.connector
import os
import queue
import threading
import uuid

from flask import Flask, flash, redirect, render_template, request, session, url_for
from functools import wraps

from simulation import auto_scale_buses, lock_sweeper

app = Flask(__name__)
app.secret_key = "replace-with-a-secure-key"

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'your_new_password',
    'database': 'bus_booking_system',
    'ssl_disabled': True,
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def get_upcoming_dates(days=7):
    today = date.today()
    return [today + timedelta(days=i) for i in range(days)]


def get_user_by_username(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, role FROM Users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return {'user_id': row[0], 'username': row[1], 'role': row[2]}
    return None


def create_user(username, role='VISITOR'):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        user_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO Users (user_id, role, username, is_active_today) VALUES (%s, %s, %s, FALSE)",
            (user_id, role, username),
        )
        conn.commit()
        return {'user_id': user_id, 'username': username, 'role': role}
    except mysql.connector.Error:
        conn.rollback()
        return None
    finally:
        cursor.close()
        conn.close()


def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = session.get('user')
            if not user:
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('login'))
            if role and user.get('role') != role:
                flash('Access denied.', 'danger')
                return redirect(url_for('index'))
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.context_processor
def inject_user():
    return {'current_user': session.get('user')}


def fetch_user_bookings(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT
            b.booking_id,
            b.booking_date,
            s.seat_number,
            d.bus_sn,
            d.date AS travel_date,
            b.status
        FROM Booking b
        JOIN SeatAvailability s ON b.seat_id = s.seat_id
        JOIN DailyBus d ON s.daily_bus_id = d.daily_bus_id
        WHERE b.user_id = %s
          AND b.status = 'CONFIRMED'
        ORDER BY b.booking_date, d.bus_sn, s.seat_number
        """,
        (user_id,),
    )
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()
    return bookings


def cancel_booking(user_id, booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT seat_id, booking_date FROM Booking WHERE booking_id = %s AND user_id = %s AND status = 'CONFIRMED'",
            (booking_id, user_id),
        )
        booking = cursor.fetchone()
        if not booking:
            return False, 'Booking not found or already cancelled.'

        seat_id, booking_date = booking
        cursor.execute(
            "UPDATE Booking SET status = 'CANCELLED' WHERE booking_id = %s",
            (booking_id,),
        )
        cursor.execute(
            "UPDATE SeatAvailability SET status = 'AVAILABLE', locked_by = NULL, lock_expires_at = NULL WHERE seat_id = %s",
            (seat_id,),
        )
        cursor.execute(
            "UPDATE DailyMetrics SET booked_seats = GREATEST(booked_seats - 1, 0) WHERE date = %s",
            (booking_date,),
        )
        cursor.execute(
            "SELECT booked_seats, active_buses FROM DailyMetrics WHERE date = %s",
            (booking_date,),
        )
        metrics = cursor.fetchone()
        if metrics:
            booked_seats, active_buses = metrics
            new_load = booked_seats / (active_buses * 10) if active_buses and active_buses > 0 else 0.0
            cursor.execute(
                "UPDATE DailyMetrics SET load_factor = %s WHERE date = %s",
                (new_load, booking_date),
            )
        conn.commit()
        return True, 'Your booking was cancelled successfully.'
    except mysql.connector.Error as err:
        conn.rollback()
        return False, f'Database error: {err}'
    finally:
        cursor.close()
        conn.close()


def merge_two_active_buses(target_date):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT load_factor, active_buses, booked_seats FROM DailyMetrics WHERE date = %s", (target_date,))
        row = cursor.fetchone()
        if not row:
            return False, 'No metrics found for that date.'

        load_factor, active_buses, booked_seats = row
        if load_factor > 0.20:
            return False, 'Merge is only allowed when load factor is 0.20 or lower.'
        if active_buses <= 1:
            return False, 'Not enough active buses to merge.'

        cursor.execute(
            "SELECT daily_bus_id, group_id FROM DailyBus WHERE date = %s AND status = 'ACTIVE' ORDER BY bus_sn LIMIT 2",
            (target_date,),
        )
        buses = cursor.fetchall()
        if len(buses) < 2:
            return False, 'There are fewer than two active buses for this date.'

        bus1_id, group1_id = buses[0]
        bus2_id, group2_id = buses[1]

        cursor.execute(
            """
            SELECT s1.seat_number
            FROM SeatAvailability s1
            JOIN SeatAvailability s2 ON s1.seat_number = s2.seat_number
            WHERE s1.daily_bus_id = %s
              AND s2.daily_bus_id = %s
              AND s1.status IN ('BOOKED', 'LOCKED')
              AND s2.status IN ('BOOKED', 'LOCKED')
            """,
            (bus1_id, bus2_id),
        )
        collisions = cursor.fetchall()
        if collisions:
            seat_list = ', '.join(str(item[0]) for item in collisions)
            return False, f'Merge aborted: conflicting seat numbers locked/booked on both buses: {seat_list}.'

        cursor.execute(
            "UPDATE DailyBusGroup SET status = 'ALTERATION_IN_PROCESS' WHERE group_id IN (%s, %s)",
            (group1_id, group2_id),
        )
        conn.commit()

        cursor.execute(
            "UPDATE DailyBus SET group_id = %s, status = 'INACTIVE' WHERE daily_bus_id = %s",
            (group1_id, bus2_id),
        )
        new_active_buses = active_buses - 1
        new_load = booked_seats / (new_active_buses * 10) if new_active_buses > 0 else 0.0
        cursor.execute(
            "UPDATE DailyMetrics SET active_buses = %s, load_factor = %s WHERE date = %s",
            (new_active_buses, new_load, target_date),
        )
        cursor.execute(
            "UPDATE DailyBusGroup SET status = 'NORMAL' WHERE group_id = %s",
            (group1_id,),
        )
        conn.commit()
        return True, 'Merge completed successfully. One bus was deactivated.'
    except mysql.connector.Error as err:
        conn.rollback()
        return False, f'Database error: {err}'
    finally:
        cursor.close()
        conn.close()


def bus_group_is_alteration_in_process(daily_bus_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT g.status
        FROM DailyBus db
        JOIN DailyBusGroup g ON db.group_id = g.group_id
        WHERE db.daily_bus_id = %s
        """,
        (daily_bus_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(row and row[0] == 'ALTERATION_IN_PROCESS')


def list_buses_for_date(target_date):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT
            db.daily_bus_id,
            db.bus_sn,
            db.status,
            g.status AS group_status,
            COUNT(sa.seat_id) AS total_seats,
            SUM(CASE WHEN g.status = 'NORMAL' AND sa.status = 'AVAILABLE' THEN 1 ELSE 0 END) AS available_seats
        FROM DailyBus db
        JOIN DailyBusGroup g ON db.group_id = g.group_id
        LEFT JOIN SeatAvailability sa ON sa.daily_bus_id = db.daily_bus_id
        WHERE db.date = %s
          AND db.status = 'ACTIVE'
        GROUP BY db.daily_bus_id, db.bus_sn, db.status, g.status
        ORDER BY db.bus_sn
    """
    cursor.execute(query, (target_date,))
    buses = cursor.fetchall()
    cursor.close()
    conn.close()
    for bus in buses:
        bus['available_seats'] = int(bus['available_seats'] or 0)
        bus['total_seats'] = int(bus['total_seats'] or 0)
    return buses


def set_user_active_status(user_id, is_active):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE Users SET is_active_today = %s WHERE user_id = %s",
            (is_active, user_id),
        )
        conn.commit()
    except mysql.connector.Error:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def get_current_active_visitor_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM Users WHERE role = 'VISITOR' AND is_active_today = TRUE"
    )
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return int(count)


def get_daily_metrics(target_date):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT load_factor, active_buses, booked_seats, visitor_count FROM DailyMetrics WHERE date = %s",
        (target_date,),
    )
    metrics = cursor.fetchone() or {'load_factor': 0.0, 'active_buses': 0, 'booked_seats': 0, 'visitor_count': 0}
    cursor.close()
    conn.close()
    metrics['load_factor'] = float(metrics.get('load_factor', 0.0) or 0.0)
    metrics['visitor_count'] = get_current_active_visitor_count()
    return metrics


def fetch_available_seats(daily_bus_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT sa.seat_number
        FROM SeatAvailability sa
        JOIN DailyBus db ON sa.daily_bus_id = db.daily_bus_id
        JOIN DailyBusGroup g ON db.group_id = g.group_id
        WHERE sa.daily_bus_id = %s
          AND sa.status = 'AVAILABLE'
          AND g.status = 'NORMAL'
        ORDER BY sa.seat_number
        """,
        (daily_bus_id,),
    )
    seats = [row['seat_number'] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return seats


def user_has_booking_for_date(user_id, booking_date):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT booking_id FROM Booking WHERE user_id = %s AND booking_date = %s AND status = 'CONFIRMED'",
        (user_id, booking_date),
    )
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result is not None


def book_seat(daily_bus_id, seat_number, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        conn.start_transaction()

        cursor.execute(
            """
            SELECT db.date, g.status
            FROM DailyBus db
            JOIN DailyBusGroup g ON db.group_id = g.group_id
            WHERE db.daily_bus_id = %s
            """,
            (daily_bus_id,),
        )
        date_row = cursor.fetchone()
        if not date_row:
            conn.rollback()
            return False, "Could not determine the booking date."

        booking_date, group_status = date_row
        if group_status == 'ALTERATION_IN_PROCESS':
            conn.rollback()
            return False, "Bus alteration in process. Booking is temporarily unavailable."

        cursor.execute(
            """
            SELECT booking_id
            FROM Booking
            WHERE user_id = %s AND booking_date = %s AND status = 'CONFIRMED'
            FOR UPDATE
            """,
            (user_id, booking_date),
        )
        if cursor.fetchone():
            conn.rollback()
            return False, "You already have a booking for this date. Cancel your existing booking to book a different seat."

        cursor.execute(
            """
            SELECT seat_id
            FROM SeatAvailability
            WHERE daily_bus_id = %s AND seat_number = %s AND status = 'AVAILABLE'
            FOR UPDATE SKIP LOCKED
            """,
            (daily_bus_id, seat_number),
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return False, "That seat is already booked or temporarily locked. Please choose another one."

        seat_id = row[0]
        booking_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO Booking (booking_id, user_id, seat_id, booking_date, status) VALUES (%s, %s, %s, %s, 'CONFIRMED')",
            (booking_id, user_id, seat_id, booking_date),
        )
        cursor.execute(
            "UPDATE SeatAvailability SET status = 'BOOKED', locked_by = NULL, lock_expires_at = NULL WHERE seat_id = %s",
            (seat_id,),
        )
        cursor.execute(
            "SELECT booked_seats, active_buses FROM DailyMetrics WHERE date = %s FOR UPDATE",
            (booking_date,),
        )
        metrics = cursor.fetchone()
        if metrics:
            booked_seats, active_buses = metrics
            new_booked = booked_seats + 1
            new_load_factor = new_booked / (active_buses * 10) if active_buses and active_buses > 0 else 0.0
            cursor.execute(
                "UPDATE DailyMetrics SET booked_seats = %s, load_factor = %s WHERE date = %s",
                (new_booked, new_load_factor, booking_date),
            )

        conn.commit()
        return True, f"Seat {seat_number} successfully booked."
    except mysql.connector.Error as err:
        conn.rollback()
        return False, f"Database error: {err}"
    finally:
        cursor.close()
        conn.close()


@app.route("/")
def index():
    dates = get_upcoming_dates()
    selected_date = request.args.get('date') or dates[0].isoformat()
    buses = list_buses_for_date(selected_date)
    metrics = get_daily_metrics(selected_date)
    return render_template(
        'index.html',
        dates=dates,
        selected_date=selected_date,
        buses=buses,
        metrics=metrics,
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if not username:
            flash('Please enter your username.', 'warning')
            return redirect(url_for('login'))

        user = get_user_by_username(username)
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('login'))

        session['user'] = user
        set_user_active_status(user['user_id'], True)
        flash(f"Logged in as {user['username']} ({user['role']}).", 'success')
        return redirect(url_for('index'))

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if not username:
            flash('Please enter a username.', 'warning')
            return redirect(url_for('register'))

        if get_user_by_username(username):
            flash('Username already exists. Please choose another.', 'danger')
            return redirect(url_for('register'))

        user = create_user(username)
        if not user:
            flash('Registration failed. Please try again.', 'danger')
            return redirect(url_for('register'))

        session['user'] = user
        set_user_active_status(user['user_id'], True)
        flash(f"Registration successful. Logged in as {user['username']}.", 'success')
        return redirect(url_for('dashboard'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    user = session.get('user')
    if user:
        set_user_active_status(user['user_id'], False)
    session.pop('user', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required()
def dashboard():
    user = session['user']
    bookings = []
    merge_message = None

    if user['role'] == 'VISITOR':
        bookings = fetch_user_bookings(user['user_id'])
    elif user['role'] == 'ADMIN':
        today = date.today().isoformat()
        merge_message = ''

    return render_template('dashboard.html', user=user, bookings=bookings, merge_message=merge_message)


@app.route('/cancel/<booking_id>', methods=['POST'])
@login_required('VISITOR')
def cancel(booking_id):
    user = session['user']
    success, message = cancel_booking(user['user_id'], booking_id)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('dashboard'))


@app.route('/merge', methods=['POST'])
@login_required('ADMIN')
def merge():
    target_date = request.form.get('date') or date.today().isoformat()
    success, message = merge_two_active_buses(target_date)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('dashboard'))


@app.route('/book/<date>/<bus_id>', methods=['GET', 'POST'])
@login_required('VISITOR')
def book(date, bus_id):
    user = session['user']
    if bus_group_is_alteration_in_process(bus_id):
        flash('Bus alteration in process. Seats are temporarily unavailable.', 'warning')
        return redirect(url_for('index', date=date))
    available_seats = fetch_available_seats(bus_id)
    if request.method == 'POST':
        seat_number = request.form.get('seat_number')
        if not seat_number:
            flash('Please select a seat number to book.', 'warning')
            return redirect(url_for('book', date=date, bus_id=bus_id))

        success, message = book_seat(bus_id, int(seat_number), user['user_id'])
        flash(message, 'success' if success else 'danger')
        if success:
            return redirect(url_for('dashboard'))
        return redirect(url_for('book', date=date, bus_id=bus_id))

    return render_template('book.html', date=date, bus_id=bus_id, seats=available_seats, username=user['username'])


_background_stop_event = None
_background_started = False


def start_background_services():
    global _background_started, _background_stop_event
    if _background_started:
        return
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return

    _background_started = True
    _background_stop_event = threading.Event()
    log_queue = queue.Queue()
    valid_dates = get_upcoming_dates()

    for target, args in (
        (auto_scale_buses, (valid_dates, _background_stop_event, log_queue)),
        (lock_sweeper, (_background_stop_event, log_queue)),
    ):
        threading.Thread(target=target, args=args, daemon=True).start()


@app.before_request
def _ensure_background_services():
    start_background_services()


if __name__ == '__main__':
    app.run(debug=True)
