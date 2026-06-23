import mysql.connector
import uuid
from datetime import date

# Database connection configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',           # Replace with your MySQL username
    'password': 'your_new_password',   # Replace with your MySQL password
    'database': 'bus_booking_system', # Replace with your database name
    'ssl_disabled': True
}

def generate_uuid():
    return str(uuid.uuid4())

def seed_database():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        target_date = date.today()
        print(f"Seeding database for date: {target_date}...")

        # 1. Seed Users (1 Admin, 3 Visitors)
        print("Inserting Users...")
        users = [
            (generate_uuid(), 'ADMIN', 'admin_super', False),
            (generate_uuid(), 'VISITOR', 'alice_j', False),
            (generate_uuid(), 'VISITOR', 'bob_smith', False),
            (generate_uuid(), 'VISITOR', 'charlie_d', False)
        ]
        cursor.executemany(
            "INSERT INTO Users (user_id, role, username, is_active_today) VALUES (%s, %s, %s, %s)", 
            users
        )

        # 2. Seed 100 Physical Buses
        print("Inserting 100 Physical Buses...")
        buses = [(sn, 10) for sn in range(1, 101)]
        cursor.executemany("INSERT INTO Bus (bus_sn, capacity) VALUES (%s, %s)", buses)

        # 3. Seed Daily Schedules, Groups, and Seats
        print("Inserting Daily Schedules and Seats...")
        for sn in range(1, 101):
            group_id = generate_uuid()
            daily_bus_id = generate_uuid()
            
            # Bus 1-10 are ACTIVE, 11-100 are INACTIVE
            status = 'ACTIVE' if sn <= 10 else 'INACTIVE'
            
            # Create a Group for the bus
            cursor.execute(
                "INSERT INTO DailyBusGroup (group_id, date, status) VALUES (%s, %s, %s)",
                (group_id, target_date, 'NORMAL')
            )
            
            # Create the DailyBus record
            cursor.execute(
                "INSERT INTO DailyBus (daily_bus_id, date, bus_sn, group_id, status) VALUES (%s, %s, %s, %s, %s)",
                (daily_bus_id, target_date, sn, group_id, status)
            )
            
            # 4. Generate 10 Seats ONLY if the bus is ACTIVE
            if status == 'ACTIVE':
                seats = [
                    (generate_uuid(), daily_bus_id, seat_num, 'AVAILABLE') 
                    for seat_num in range(1, 11)
                ]
                cursor.executemany(
                    "INSERT INTO SeatAvailability (seat_id, daily_bus_id, seat_number, status) VALUES (%s, %s, %s, %s)",
                    seats
                )

        # 5. Initialize DailyMetrics
        print("Initializing Daily Metrics...")
        cursor.execute(
            "INSERT INTO DailyMetrics (date, visitor_count, active_buses, booked_seats, load_factor) VALUES (%s, %s, %s, %s, %s)",
            (target_date, 0, 10, 0, 0.00)
        )

        conn.commit()
        print("✅ Database successfully seeded!")

    except mysql.connector.Error as err:
        print(f"❌ Error: {err}")
        if conn:
            conn.rollback()
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    seed_database()