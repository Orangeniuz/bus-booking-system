import mysql.connector
import uuid
import time
import threading
import psutil
from concurrent.futures import ThreadPoolExecutor
from datetime import date

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'your_new_password',
    'database': 'bus_booking_system',
    'ssl_disabled': True
}

# Global dictionary to store hardware metrics
metrics = {
    "max_cpu": 0.0,
    "max_virt_mem": 0,
    "max_phys_mem": 0,
    "start_idle_time": 0.0,
    "end_idle_time": 0.0
}

def monitor_resources(stop_event):
    """Background thread to monitor CPU and Memory usage (Req 11)."""
    process = psutil.Process()
    metrics["start_idle_time"] = psutil.cpu_times().idle
    
    while not stop_event.is_set():
        # Track maximums during the run
        metrics["max_cpu"] = max(metrics["max_cpu"], psutil.cpu_percent(interval=0.1))
        metrics["max_virt_mem"] = max(metrics["max_virt_mem"], psutil.virtual_memory().used)
        metrics["max_phys_mem"] = max(metrics["max_phys_mem"], process.memory_info().rss)
        
    metrics["end_idle_time"] = psutil.cpu_times().idle

def simulate_client_booking(client_id, target_date):
    """Simulates a single client attempting to lock and book a seat (Req 3, 9, 12)."""
    # Each thread needs its own isolated database connection
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        # Step 1: Find an available seat and LOCK it
        # Note: 'FOR UPDATE SKIP LOCKED' prevents threads from queuing behind each other 
        # for the exact same row, vastly improving concurrency performance.
        cursor.execute("""
            SELECT s.seat_id, s.daily_bus_id 
            FROM SeatAvailability s
            JOIN DailyBus d ON s.daily_bus_id = d.daily_bus_id
            WHERE d.date = %s AND s.status = 'AVAILABLE'
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """, (target_date,))
        
        row = cursor.fetchone()
        
        if not row:
            print(f"Client {client_id[-4:]}: No available seats found.")
            return False
            
        seat_id, daily_bus_id = row
        
        # Step 2: Update status to 'LOCKED' (Simulating the 5-minute hold)
        cursor.execute("""
            UPDATE SeatAvailability 
            SET status = 'LOCKED', locked_by = %s, lock_expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE)
            WHERE seat_id = %s
        """, (client_id, seat_id))
        conn.commit()
        
        print(f"Client {client_id[-4:]}: LOCKED seat {seat_id[-4:]} for 5 minutes.")
        
        # Simulating user taking time to fill out checkout forms (e.g., 1 second)
        time.sleep(1) 
        
        # Step 3: Finalize Booking
        booking_id = str(uuid.uuid4())
        
        # Insert confirmed ticket
        cursor.execute("""
            INSERT INTO Booking (booking_id, user_id, seat_id, booking_date, status)
            VALUES (%s, %s, %s, %s, 'CONFIRMED')
        """, (booking_id, client_id, seat_id, target_date))
        
        # Update seat to BOOKED
        cursor.execute("""
            UPDATE SeatAvailability 
            SET status = 'BOOKED' 
            WHERE seat_id = %s
        """, (seat_id,))
        
        conn.commit()
        print(f"Client {client_id[-4:]}: ✅ SUCCESSFULLY BOOKED seat {seat_id[-4:]}.")
        return True
        
    except mysql.connector.Error as err:
        print(f"Client {client_id[-4:]}: ❌ Database Error: {err}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def run_simulation(num_clients):
    print("--- Starting Concurrency Simulation ---")
    target_date = date.today()
    
    # Generate mock client UUIDs for the simulation
    clients = [str(uuid.uuid4()) for _ in range(num_clients)]
    
    # Seed the mock clients into the database temporarily to satisfy Foreign Key constraints
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT IGNORE INTO Users (user_id, role, username) VALUES (%s, 'VISITOR', %s)",
        [(c_id, f"sim_user_{c_id[-4:]}") for c_id in clients]
    )
    conn.commit()
    conn.close()

    # Start Resource Monitor
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=monitor_resources, args=(stop_event,))
    monitor_thread.start()

    # Launch Thread Pool for parallel clients (Req 10b)
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        # Map clients to the booking function concurrently
        futures = [executor.submit(simulate_client_booking, c_id, target_date) for c_id in clients]
        
        # Wait for all threads to complete
        for future in futures:
            future.result()
            
    execution_time = time.time() - start_time

    # Stop Resource Monitor
    stop_event.set()
    monitor_thread.join()

    # Calculate and Print System Metrics (Req 11)
    cpu_idle_diff = metrics["end_idle_time"] - metrics["start_idle_time"]
    
    print("\n--- Simulation Complete ---")
    print(f"Total Execution Time : {execution_time:.2f} seconds")
    print(f"Total Clients Served : {num_clients}")
    print("\n--- System Resource Metrics ---")
    print(f"Maximum CPU Usage    : {metrics['max_cpu']}%")
    print(f"CPU Idle Time Passed : {cpu_idle_diff:.2f} seconds")
    print(f"Max Virtual Memory   : {metrics['max_virt_mem'] / (1024 * 1024):.2f} MB")
    print(f"Max Physical Memory  : {metrics['max_phys_mem'] / (1024 * 1024):.2f} MB")

if __name__ == "__main__":
    # Simulate 120 concurrent clients rushing to book seats
    run_simulation(num_clients=120)