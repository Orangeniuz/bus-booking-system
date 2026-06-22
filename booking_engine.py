import mysql.connector
from mysql.connector import Error

STARTING_DAILY_BUS_LIMIT = 10
EXTRA_LOAD_FACTOR_THRESHOLD = 0.8
MAX_FLEET_LIMIT = 100


def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        database='bus_booking_system',
        user='root',
        password='your_new_password',
        ssl_disabled=True
    )


def request_seat(visitor_id, trip_id, seat_id):
    # Initialize conn to None so the except block doesn't crash if connection fails
    conn = None 
    
    try:
        conn = get_db_connection()
        
        if not conn.is_connected():
            return False

        cursor = conn.cursor()

        # 2. START THE TRANSACTION
        # This ensures all following queries are treated as a single operation
        cursor.execute("START TRANSACTION;")

        # 3. ATTEMPT TO LOCK THE RECORD
        # FOR UPDATE tells MySQL: "Lock this row. If another thread is trying to read or write to this row, make them wait until I am done."
        check_query = """
            SELECT id, booking_status, lock_expires_at 
            FROM Booking 
            WHERE trip_id = %s AND seat_id = %s 
            FOR UPDATE;
        """
        cursor.execute(check_query, (trip_id, seat_id))
        result = cursor.fetchone()

        # 4. EVALUATE THE SEAT'S STATUS
        if result is None:
            # Scenario A: The seat has never been interacted with. It is totally free.
            insert_query = """
                INSERT INTO Booking (visitor_id, trip_id, seat_id, booking_status, lock_expires_at) 
                VALUES (%s, %s, %s, 'Pending', DATE_ADD(NOW(), INTERVAL 5 MINUTE));
            """
            cursor.execute(insert_query, (visitor_id, trip_id, seat_id))
            print(f"Success: Seat locked for Visitor {visitor_id}.")

        else:
            booking_id, status, expires_at = result
            
            # Scenario B: A record exists. We must check if it is active or expired.
            # We use MySQL's NOW() in a separate query, or handle the datetime logic in Python.
            # To keep it completely precise to the database server's clock, let's use a SQL check.
            
            check_expiry_query = """
                SELECT IF(lock_expires_at < NOW(), 1, 0) AS is_expired 
                FROM Booking WHERE id = %s;
            """
            cursor.execute(check_expiry_query, (booking_id,))
            is_expired = cursor.fetchone()[0]

            if status == 'Cancelled' or (status == 'Pending' and is_expired == 1):
                # The previous lock expired or was cancelled! We can safely overwrite it.
                update_query = """
                    UPDATE Booking 
                    SET visitor_id = %s, booking_status = 'Pending', lock_expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE) 
                    WHERE id = %s;
                """
                cursor.execute(update_query, (visitor_id, booking_id))
                print(f"Success: Previous lock expired. Seat claimed by Visitor {visitor_id}.")
            else:
                # Scenario C: The seat is actively 'Booked', or 'Pending' and not yet expired.
                print(f"Failed: Seat is currently locked or booked by someone else.")
                conn.rollback()
                return False

        # 5. COMMIT THE TRANSACTION
        # This saves the changes and releases the row lock for other threads
        conn.commit()
        return True

    except Error as e:
        print(f"Database Error: {e}")
        # Safely check if conn exists before trying to roll back
        if conn is not None and conn.is_connected():
            conn.rollback()
        return False
        
    finally:
        # Safely check if conn exists before closing
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()

# --- Confirm a pending booking ---
def confirm_booking(visitor_id, trip_id, seat_id):
    """
    Upgrades a 'Pending' seat to 'Booked' permanently.
    Fails if the 5-minute lock has expired.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn.is_connected():
            return False

        cursor = conn.cursor()
        
        # We only update if it is Pending AND hasn't expired yet
        update_query = """
            UPDATE Booking 
            SET booking_status = 'Booked', lock_expires_at = NULL 
            WHERE visitor_id = %s AND trip_id = %s AND seat_id = %s 
            AND booking_status = 'Pending' AND lock_expires_at >= NOW();
        """
        cursor.execute(update_query, (visitor_id, trip_id, seat_id))
        conn.commit()

        # cursor.rowcount tells us how many rows were actually changed
        if cursor.rowcount > 0:
            print(f"Success: Seat permanently booked for Visitor {visitor_id}.")
            return True
        else:
            print(f"Failed: Lock expired or no pending booking found for Visitor {visitor_id}.")
            return False

    except Error as e:
        print(f"Database Error: {e}")
        if conn is not None and conn.is_connected():
            conn.rollback()
        return False
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()

# --- Cancel a pending booking ---
def cancel_booking(visitor_id, trip_id, seat_id):
    """
    Changes a 'Pending' or 'Booked' seat to 'Cancelled', freeing it up.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn.is_connected():
            return False

        cursor = conn.cursor()
        
        # We only cancel if it belongs to this visitor and isn't already cancelled
        update_query = """
            UPDATE Booking 
            SET booking_status = 'Cancelled' 
            WHERE visitor_id = %s AND trip_id = %s AND seat_id = %s 
            AND booking_status IN ('Pending', 'Booked');
        """
        cursor.execute(update_query, (visitor_id, trip_id, seat_id))
        conn.commit()

        if cursor.rowcount > 0:
            print(f"Success: Booking cancelled for Visitor {visitor_id}. Seat is now available.")
            return True
        else:
            print(f"Failed: No active booking found to cancel for Visitor {visitor_id}.")
            return False

    except Error as e:
        print(f"Database Error: {e}")
        if conn is not None and conn.is_connected():
            conn.rollback()
        return False
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()

# --- Scale buses when load is high ---
def scale_buses_if_needed(target_date_str):
    """
    Calculates the load factor for a specific date (YYYY-MM-DD).
    If the day has fewer than STARTING_DAILY_BUS_LIMIT buses, it will schedule enough
    buses to reach that starting capacity. Once the starting limit is met, it only
    adds a new bus when load factor exceeds EXTRA_LOAD_FACTOR_THRESHOLD.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn.is_connected():
            return False

        cursor = conn.cursor(dictionary=True)
        cursor.execute("START TRANSACTION;")

        # 1. Count the current number of scheduled buses for the date
        cursor.execute("SELECT COUNT(*) AS daily_bus_count FROM Trip WHERE DATE(trip_date) = %s;", (target_date_str,))
        daily_bus_count = cursor.fetchone()['daily_bus_count'] or 0

        # 2. Calculate the load factor for the specific day
        load_query = """
            SELECT 
                (SELECT COUNT(*) 
                 FROM Booking b 
                 JOIN Trip t ON b.trip_id = t.id 
                 WHERE DATE(t.trip_date) = %s AND b.booking_status = 'Booked') AS booked_seats,
                 
                (SELECT SUM(bus.total_seats) 
                 FROM Trip t 
                 JOIN Bus bus ON t.bus_id = bus.id 
                 WHERE DATE(t.trip_date) = %s) AS total_capacity;
        """
        cursor.execute(load_query, (target_date_str, target_date_str))
        stats = cursor.fetchone()

        booked_seats = stats['booked_seats'] or 0
        total_capacity = stats['total_capacity'] or 0

        if total_capacity == 0:
            load_factor = 0.0
            print(f"No scheduled bus capacity yet for {target_date_str}. Starting from zero.")
        else:
            load_factor = booked_seats / total_capacity
            print(f"Current Load Factor for {target_date_str}: {load_factor:.2f} ({booked_seats}/{total_capacity})")

        if daily_bus_count < STARTING_DAILY_BUS_LIMIT:
            needed_buses = STARTING_DAILY_BUS_LIMIT - daily_bus_count
            print(
                f"Below starting daily limit: {daily_bus_count}/{STARTING_DAILY_BUS_LIMIT} buses scheduled for {target_date_str}. "
                f"Attempting to add {needed_buses} bus(es)."
            )

            while needed_buses > 0:
                find_bus_query = """
                    SELECT id FROM Bus 
                    WHERE is_active = TRUE 
                    AND id NOT IN (SELECT bus_id FROM Trip WHERE DATE(trip_date) = %s)
                    LIMIT 1 
                    FOR UPDATE;
                """
                cursor.execute(find_bus_query, (target_date_str,))
                available_bus = cursor.fetchone()

                if not available_bus:
                    print("Failed: No available standby buses remain to meet the starting daily limit.")
                    break

                new_bus_id = available_bus['id']
                cursor.execute("SELECT COUNT(*) AS total_fleet FROM Bus;")
                total_fleet = cursor.fetchone()['total_fleet']

                if total_fleet >= MAX_FLEET_LIMIT:
                    print(f"Failed: Maximum fleet limit of {MAX_FLEET_LIMIT} buses reached.")
                    break

                spawn_query = """
                    INSERT INTO Trip (bus_id, trip_date, system_status) 
                    VALUES (%s, CONCAT(%s, ' 08:00:00'), 'Active');
                """
                cursor.execute(spawn_query, (new_bus_id, target_date_str))
                print(f"Success: Bus {new_bus_id} added to the schedule for {target_date_str}.")
                daily_bus_count += 1
                needed_buses -= 1

            conn.commit()
            return daily_bus_count >= STARTING_DAILY_BUS_LIMIT

        if load_factor >= EXTRA_LOAD_FACTOR_THRESHOLD:
            print("High load detected. Attempting to add a new bus beyond the starting limit...")
        else:
            print(
                f"No additional bus added. Daily starting limit of {STARTING_DAILY_BUS_LIMIT} buses is met and "
                f"load factor {load_factor:.2f} is below the threshold of {EXTRA_LOAD_FACTOR_THRESHOLD}.")
            conn.commit()
            return True

        find_bus_query = """
            SELECT id FROM Bus 
            WHERE is_active = TRUE 
            AND id NOT IN (SELECT bus_id FROM Trip WHERE DATE(trip_date) = %s)
            LIMIT 1 
            FOR UPDATE;
        """
        cursor.execute(find_bus_query, (target_date_str,))
        available_bus = cursor.fetchone()

        if available_bus:
            new_bus_id = available_bus['id']
            cursor.execute("SELECT COUNT(*) AS total_fleet FROM Bus;")
            total_fleet = cursor.fetchone()['total_fleet']

            if total_fleet < MAX_FLEET_LIMIT:
                spawn_query = """
                    INSERT INTO Trip (bus_id, trip_date, system_status) 
                    VALUES (%s, CONCAT(%s, ' 08:00:00'), 'Active');
                """
                cursor.execute(spawn_query, (new_bus_id, target_date_str))
                print(f"Success: Bus {new_bus_id} added to the schedule for {target_date_str}.")
            else:
                print(f"Failed: Maximum fleet limit of {MAX_FLEET_LIMIT} buses reached.")
        else:
            print("Failed: No available standby buses to handle the load.")

        conn.commit()
        return True

    except Error as e:
        print(f"Database Error: {e}")
        if conn is not None and conn.is_connected():
            conn.rollback()
        return False
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()


def view_available_seats(trip_id):
    """
    CLIENT VIEW: Returns available seats for a trip.
    Blocks the user if the trip is currently undergoing a merge alteration.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn.is_connected():
            return None

        cursor = conn.cursor(dictionary=True)

        # 1. Check if the bus is currently locked by the admin
        cursor.execute("SELECT system_status FROM Trip WHERE id = %s;", (trip_id,))
        trip = cursor.fetchone()

        if not trip:
            print(f"Error: Trip {trip_id} does not exist.")
            return None

        if trip['system_status'] == 'Merging':
            # This satisfies your requirement for the UI alert
            print("ALERT: Bus alteration in process. Please wait a moment and refresh.")
            return 'LOCKED'

        # 2. If Active, fetch all seats that are NOT actively booked or holding a valid pending lock
        query = """
            SELECT s.id, s.seat_number 
            FROM Seat s
            JOIN Trip t ON s.bus_id = t.bus_id
            WHERE t.id = %s
            AND s.id NOT IN (
                SELECT seat_id FROM Booking 
                WHERE trip_id = %s 
                AND (booking_status = 'Booked' OR (booking_status = 'Pending' AND lock_expires_at >= NOW()))
            );
        """
        cursor.execute(query, (trip_id, trip_id))
        available_seats = cursor.fetchall()
        
        print(f"Success: Found {len(available_seats)} available seats for Trip {trip_id}.")
        return available_seats

    except Error as e:
        print(f"Database Error: {e}")
        return None
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()


def merge_trips(target_trip_id, source_trip_id):
    """
    ADMIN VIEW: Merges source_trip into target_trip if load factor <= 0.2 and no seat collisions exist.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn.is_connected():
            return False

        cursor = conn.cursor(dictionary=True)
        cursor.execute("START TRANSACTION;")

        # 1. Lock both trips and retrieve their associated physical bus IDs
        lock_query = """
            SELECT id, bus_id, system_status 
            FROM Trip 
            WHERE id IN (%s, %s) 
            FOR UPDATE;
        """
        cursor.execute(lock_query, (target_trip_id, source_trip_id))
        trips = cursor.fetchall()

        if len(trips) != 2:
            print("Failed: One or both trips do not exist.")
            conn.rollback()
            return False

        # Extract bus IDs for mapping later
        target_bus_id = next(t['bus_id'] for t in trips if t['id'] == target_trip_id)
        source_bus_id = next(t['bus_id'] for t in trips if t['id'] == source_trip_id)

        # 2. Immediately lock out clients by setting status to 'Merging'
        cursor.execute("UPDATE Trip SET system_status = 'Merging' WHERE id IN (%s, %s);", (target_trip_id, source_trip_id))
        
        # 3. Check Load Factor (Requirement: Combine load must be low)
        # For brevity, assuming the admin already validated the <= 0.2 rule before clicking "Merge" in the UI.

        # 4. Collision Detection Check
        # Are there any identical seat numbers booked on BOTH buses?
        collision_query = """
            SELECT s1.seat_number
            FROM Booking b1
            JOIN Seat s1 ON b1.seat_id = s1.id
            WHERE b1.trip_id = %s AND b1.booking_status IN ('Pending', 'Booked')
            AND s1.seat_number IN (
                SELECT s2.seat_number
                FROM Booking b2
                JOIN Seat s2 ON b2.seat_id = s2.id
                WHERE b2.trip_id = %s AND b2.booking_status IN ('Pending', 'Booked')
            );
        """
        cursor.execute(collision_query, (target_trip_id, source_trip_id))
        collisions = cursor.fetchall()

        if collisions:
            conflicting_seats = [c['seat_number'] for c in collisions]
            print(f"Merge Failed: Seat collisions detected on seats {conflicting_seats}. Manual intervention required.")
            conn.rollback() # Reverts the 'Merging' status so clients can view again
            return False

        # 5. Transfer Bookings (The Mapping Query)
        # We join the Seat table twice to map the source physical seat to the target physical seat based on seat_number
        transfer_query = """
            UPDATE Booking b_source
            JOIN Seat s_source ON b_source.seat_id = s_source.id
            JOIN Seat s_target ON s_source.seat_number = s_target.seat_number AND s_target.bus_id = %s
            SET b_source.trip_id = %s, b_source.seat_id = s_target.id
            WHERE b_source.trip_id = %s;
        """
        cursor.execute(transfer_query, (target_bus_id, target_trip_id, source_trip_id))
        print(f"Success: Transferred {cursor.rowcount} passenger records to Trip {target_trip_id}.")

        # 6. Delete the Empty Trip (Frees up the physical bus)
        cursor.execute("DELETE FROM Trip WHERE id = %s;", (source_trip_id,))

        # 7. Unlock the target trip for clients
        cursor.execute("UPDATE Trip SET system_status = 'Active' WHERE id = %s;", (target_trip_id,))

        conn.commit()
        print(f"Merge Complete: Trip {source_trip_id} deleted. Trip {target_trip_id} is active.")
        return True

    except Error as e:
        print(f"Database Error: {e}")
        if conn is not None and conn.is_connected():
            conn.rollback()
        return False
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()

# --- Test the functions ---
# Assuming Visitor 3 wants to interact with Seat 3 on Trip 1
# request_seat(visitor_id=3, trip_id=1, seat_id=3)
# Attempt to confirm the booking (will only succeed if still pending and not expired)
# confirm_booking(visitor_id=3, trip_id=1, seat_id=3)
# Attempt to cancel the booking (works for Pending or Booked)
# cancel_booking(visitor_id=3, trip_id=1, seat_id=3)
# Pass the date you want to check based on your seeded data
# scale_buses_if_needed('2026-07-01')