import mysql.connector
from mysql.connector import Error

def request_seat(visitor_id, trip_id, seat_id):
    # Initialize conn to None so the except block doesn't crash if connection fails
    conn = None 
    
    try:
        # Add ssl_disabled=True to bypass the outdated SSL method
        conn = mysql.connector.connect(
            host='localhost',
            database='bus_booking_system', # Update this
            user='root', # Update this
            password='your_new_password', # Update this 
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

# --- Test the function ---
# Assuming Visitor 3 wants to book Seat 3 on Trip 1
request_seat(visitor_id=3, trip_id=1, seat_id=3)