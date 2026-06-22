import mysql.connector
from mysql.connector import Error

def request_seat(visitor_id, trip_id, seat_id):
    # Initialize conn to None so the except block doesn't crash if connection fails
    conn = None 
    
    try:
        # Add ssl_disabled=True to bypass the outdated SSL method
        conn = mysql.connector.connect(
            host='localhost',
            database='bus_booking_system',
            user='root',
            password='your_new_password',
            ssl_disabled=True
        )
        
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
        conn = mysql.connector.connect(
            host='localhost',
            database='bus_booking_system',
            user='root',
            password='your_new_password',
            ssl_disabled=True
        )
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
        conn = mysql.connector.connect(
            host='localhost',
            database='bus_booking_system',
            user='root',
            password='your_new_password',
            ssl_disabled=True
        )
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
    If load factor >= 0.8, it schedules a new bus for that day up to the limit.
    """
    conn = None
    try:
        conn = mysql.connector.connect(
            host='localhost',
            database='bus_booking_system',
            user='root',
            password='your_new_password',
            ssl_disabled=True
        )
        if not conn.is_connected():
            return False

        cursor = conn.cursor(dictionary=True)
        cursor.execute("START TRANSACTION;")

        # 1. Calculate Load Factor for the specific day
        # We use DATE() to ignore the exact time and group by the calendar day
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

        # Avoid division by zero if no buses are scheduled at all
        if total_capacity == 0:
            print(f"No buses scheduled for {target_date_str}.")
            conn.rollback()
            return False

        load_factor = booked_seats / total_capacity
        print(f"Current Load Factor for {target_date_str}: {load_factor:.2f} ({booked_seats}/{total_capacity})")

        # 2. Check Threshold
        if load_factor >= 0.8:
            print("High load detected. Attempting to add a new bus...")

            # 3. Find an available bus NOT already scheduled for this day
            # FOR UPDATE locks the bus row so another parallel thread doesn't grab the same bus
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
                
                # 4. Check global limit (e.g., max 100 physical buses in the fleet)
                cursor.execute("SELECT COUNT(*) AS total_fleet FROM Bus;")
                total_fleet = cursor.fetchone()['total_fleet']
                
                if total_fleet <= 100:
                    # 5. Spawn the new Trip
                    # Defaulting to 08:00:00 for the new trip time, adjust as needed
                    spawn_query = """
                        INSERT INTO Trip (bus_id, trip_date, system_status) 
                        VALUES (%s, CONCAT(%s, ' 08:00:00'), 'Active');
                    """
                    cursor.execute(spawn_query, (new_bus_id, target_date_str))
                    print(f"Success: Bus {new_bus_id} added to the schedule for {target_date_str}.")
                else:
                    print("Failed: Maximum fleet limit of 100 buses reached.")
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

# --- Test the functions ---
# Assuming Visitor 3 wants to interact with Seat 3 on Trip 1
# request_seat(visitor_id=3, trip_id=1, seat_id=3)
# Attempt to confirm the booking (will only succeed if still pending and not expired)
# confirm_booking(visitor_id=3, trip_id=1, seat_id=3)
# Attempt to cancel the booking (works for Pending or Booked)
# cancel_booking(visitor_id=3, trip_id=1, seat_id=3)
# Pass the date you want to check based on your seeded data
# scale_buses_if_needed('2026-07-01')