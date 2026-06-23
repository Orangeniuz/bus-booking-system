import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from booking_engine import (
    get_db_connection,
    authenticate_admin,
    get_daily_load_status,
    view_available_seats,
    request_seat,
    confirm_booking,
    cancel_booking,
    merge_trips,
    scale_buses_if_needed,
)

app = Flask(__name__)
app.secret_key = os.environ.get('BUS_BOOKING_SECRET_KEY', 'change-this-secret')


def login_required(role=None):
    def wrapper(fn):
        def decorated(*args, **kwargs):
            if 'user_role' not in session:
                return redirect(url_for('login'))
            if role and session.get('user_role') != role:
                flash('Access denied.', 'error')
                return redirect(url_for('login'))
            return fn(*args, **kwargs)
        decorated.__name__ = fn.__name__
        return decorated
    return wrapper


def create_new_visitor():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO Visitor () VALUES ();')
    conn.commit()
    visitor_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return visitor_id


def get_visitor(visitor_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT id FROM Visitor WHERE id = %s;', (visitor_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_all_trips():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        '''
        SELECT t.id, DATE(t.trip_date) AS trip_date, t.system_status, bus.id AS bus_id, bus.total_seats,
            (SELECT COUNT(*) FROM Booking b WHERE b.trip_id = t.id AND b.booking_status = 'Booked') AS booked_seats,
            (SELECT COUNT(*) FROM Booking b WHERE b.trip_id = t.id AND b.booking_status = 'Pending' AND b.lock_expires_at >= NOW()) AS pending_locks
        FROM Trip t
        JOIN Bus bus ON t.bus_id = bus.id
        ORDER BY t.trip_date, t.id;
        '''
    )
    trips = cursor.fetchall()
    cursor.close()
    conn.close()
    return trips


def get_client_bookings(visitor_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        '''
        SELECT b.id AS booking_id, t.id AS trip_id, DATE(t.trip_date) AS trip_date, s.id AS seat_id, s.seat_number,
            b.booking_status, b.lock_expires_at
        FROM Booking b
        JOIN Trip t ON b.trip_id = t.id
        JOIN Seat s ON b.seat_id = s.id
        WHERE b.visitor_id = %s
        ORDER BY t.trip_date, b.id;
        ''',
        (visitor_id,)
    )
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()
    return bookings


def get_trip_bookings(trip_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        '''
        SELECT b.id AS booking_id, b.visitor_id, s.seat_number, b.booking_status, b.lock_expires_at
        FROM Booking b
        JOIN Seat s ON b.seat_id = s.id
        WHERE b.trip_id = %s
        ORDER BY s.seat_number, b.booking_status;
        ''',
        (trip_id,)
    )
    bookings = cursor.fetchall()
    cursor.close()
    conn.close()
    return bookings


def get_trip_details(trip_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        '''
        SELECT t.id, DATE(t.trip_date) AS trip_date, t.system_status, bus.id AS bus_id, bus.total_seats
        FROM Trip t
        JOIN Bus bus ON t.bus_id = bus.id
        WHERE t.id = %s;
        ''',
        (trip_id,)
    )
    trip = cursor.fetchone()
    cursor.close()
    conn.close()
    return trip


@app.route('/')
def home():
    if 'user_role' in session:
        if session['user_role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('client_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form.get('role')
        if role == 'admin':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            if authenticate_admin(username, password):
                session['user_role'] = 'admin'
                session['username'] = username
                flash('Admin login successful.', 'success')
                return redirect(url_for('admin_dashboard'))
            flash('Invalid admin credentials.', 'error')
        elif role == 'client':
            visitor_id = request.form.get('visitor_id')
            if visitor_id:
                try:
                    visitor_id = int(visitor_id)
                except ValueError:
                    flash('Visitor ID must be a number.', 'error')
                    return render_template('login.html')
                if get_visitor(visitor_id) is None:
                    flash('Visitor not found. Leave blank to create a new client.', 'error')
                    return render_template('login.html')
            else:
                visitor_id = create_new_visitor()
                flash(f'New client created with Visitor ID {visitor_id}.', 'success')

            session['user_role'] = 'client'
            session['visitor_id'] = visitor_id
            flash(f'Client login successful. Your Visitor ID is {visitor_id}.', 'success')
            return redirect(url_for('client_dashboard'))
        else:
            flash('Please choose client or admin login.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/client')
@login_required(role='client')
def client_dashboard():
    visitor_id = session.get('visitor_id')
    trips = get_all_trips()
    bookings = get_client_bookings(visitor_id)
    return render_template('client_dashboard.html', visitor_id=visitor_id, trips=trips, bookings=bookings)


@app.route('/client/trip/<int:trip_id>')
@login_required(role='client')
def client_view_trip(trip_id):
    visitor_id = session.get('visitor_id')
    trip = get_trip_details(trip_id)
    if not trip:
        flash('Trip not found.', 'error')
        return redirect(url_for('client_dashboard'))

    available_seats = view_available_seats(trip_id)
    locked_message = None
    if available_seats == 'LOCKED':
        locked_message = 'Bus alteration in process. Please refresh later.'
        available_seats = []

    return render_template(
        'seat_selection.html',
        trip=trip,
        available_seats=available_seats,
        locked_message=locked_message,
        visitor_id=visitor_id,
    )


@app.route('/client/book/<int:trip_id>/<int:seat_id>', methods=['POST'])
@login_required(role='client')
def client_book_seat(trip_id, seat_id):
    visitor_id = session.get('visitor_id')
    success = request_seat(visitor_id, trip_id, seat_id)
    if success:
        flash('Seat locked successfully. Complete booking or cancel from your dashboard.', 'success')
    else:
        flash('Unable to lock the selected seat. It may already be in use.', 'error')
    return redirect(url_for('client_view_trip', trip_id=trip_id))


@app.route('/client/confirm/<int:trip_id>/<int:seat_id>', methods=['POST'])
@login_required(role='client')
def client_confirm_booking(trip_id, seat_id):
    visitor_id = session.get('visitor_id')
    success = confirm_booking(visitor_id, trip_id, seat_id)
    if success:
        flash('Booking confirmed.', 'success')
    else:
        flash('Unable to confirm. The pending reservation may have expired.', 'error')
    return redirect(url_for('client_dashboard'))


@app.route('/client/cancel/<int:booking_id>', methods=['POST'])
@login_required(role='client')
def client_cancel_booking(booking_id):
    visitor_id = session.get('visitor_id')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        'SELECT trip_id, seat_id FROM Booking WHERE id = %s AND visitor_id = %s;', (booking_id, visitor_id)
    )
    booking = cursor.fetchone()
    cursor.close()
    conn.close()

    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('client_dashboard'))

    success = cancel_booking(visitor_id, booking['trip_id'], booking['seat_id'])
    if success:
        flash('Booking cancelled.', 'success')
    else:
        flash('Unable to cancel booking.', 'error')
    return redirect(url_for('client_dashboard'))


@app.route('/admin')
@login_required(role='admin')
def admin_dashboard():
    trips = get_all_trips()
    today = datetime.today().strftime('%Y-%m-%d')
    load_status = get_daily_load_status(today)
    return render_template(
        'admin_dashboard.html',
        username=session.get('username'),
        trips=trips,
        today=today,
        load_status=load_status,
    )


@app.route('/admin/refresh/<date_str>')
@login_required(role='admin')
def admin_refresh(date_str):
    success = scale_buses_if_needed(date_str)
    if success:
        flash(f'Scale check complete for {date_str}.', 'success')
    else:
        flash('Unable to refresh the schedule.', 'error')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/trip/<int:trip_id>')
@login_required(role='admin')
def admin_view_trip(trip_id):
    trip = get_trip_details(trip_id)
    if not trip:
        flash('Trip not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    bookings = get_trip_bookings(trip_id)
    return render_template('admin_trip.html', trip=trip, bookings=bookings)


@app.route('/admin/merge', methods=['GET', 'POST'])
@login_required(role='admin')
def admin_merge():
    trips = get_all_trips()
    if request.method == 'POST':
        target_trip_id = request.form.get('target_trip_id')
        source_trip_id = request.form.get('source_trip_id')
        if not target_trip_id or not source_trip_id or target_trip_id == source_trip_id:
            flash('Please choose two different trips to merge.', 'error')
            return render_template('admin_merge.html', trips=trips)
        success = merge_trips(int(target_trip_id), int(source_trip_id))
        if success:
            flash('Trips merged successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Merge failed. Check the load factor and seat collision requirements.', 'error')
    return render_template('admin_merge.html', trips=trips)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
