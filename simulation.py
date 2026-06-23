import mysql.connector
import uuid
import time
import threading
import psutil
import queue
import random
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

# Global queue for asynchronous logging
log_queue = queue.Queue()

def monitor_resources(stop_event):
    """Background thread to monitor CPU and Memory usage (Req 11)."""
    process = psutil.Process()
    metrics["start_idle_time"] = psutil.cpu_times().idle
    
    while not stop_event.is_set():
        metrics["max_cpu"] = max(metrics["max_cpu"], psutil.cpu_percent(interval=0.1))
        metrics["max_virt_mem"] = max(metrics["max_virt_mem"], psutil.virtual_memory().used)
        metrics["max_phys_mem"] = max(metrics["max_phys_mem"], process.memory_info().rss)
        
    metrics["end_idle_time"] = psutil.cpu_times().idle

def async_logger(stop_event, batch_size=50):
    """Consumer Thread: Reads from queue and writes to disk in batches (Req 13, 14, 15)."""
    buffer = []
    
    with open("archive_activity.log", "a") as log_file:
        while not stop_event.is_set() or not log_queue.empty():
            try:
                msg = log_queue.get(timeout=0.1)
                buffer.append(msg)
                
                if len(buffer) >= batch_size:
                    log_file.write("\n".join(buffer) + "\n")
                    log_file.flush()
                    buffer.clear()
            except queue.Empty:
                continue

        if buffer:
            log_file.write("\n".join(buffer) + "\n")
            log_file.flush()

def auto_scale_buses(target_date, stop_event):
    """Background daemon tracking load factor to activate extra buses (Req 4)."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    while not stop_event.is_set():
        try:
            cursor.execute("SELECT load_factor, active_buses FROM DailyMetrics WHERE date = %s", (target_date,))
            row = cursor.fetchone()
            
            if row:
                load_factor, active_buses = row
                
                if load_factor >= 0.8 and active_buses < 100:
                    log_queue.put(f"[{time.time()}] ⚠️ LOAD HIGH ({load_factor}). Activating 2 new buses...")
                    
                    cursor.execute("""
                        SELECT daily_bus_id FROM DailyBus 
                        WHERE date = %s AND status = 'INACTIVE' 
                        ORDER BY bus_sn ASC LIMIT 2
                    """, (target_date,))
                    
                    buses_to_activate = cursor.fetchall()
                    
                    if buses_to_activate:
                        bus_ids = [b[0] for b in buses_to_activate]
                        format_strings = ','.join(['%s'] * len(bus_ids))
                        
                        cursor.execute(f"""
                            UPDATE DailyBus SET status = 'ACTIVE' 
                            WHERE daily_bus_id IN ({format_strings})
                        """, tuple(bus_ids))
                        
                        new_seats = []
                        for b_id in bus_ids:
                            for seat_num in range(1, 11):
                                new_seats.append((str(uuid.uuid4()), b_id, seat_num, 'AVAILABLE'))
                        
                        cursor.executemany("""
                            INSERT INTO SeatAvailability (seat_id, daily_bus_id, seat_number, status) 
                            VALUES (%s, %s, %s, %s)
                        """, new_seats)
                        
                        cursor.execute("""
                            UPDATE DailyMetrics 
                            SET active_buses = active_buses + %s,
                                load_factor = booked_seats / ((active_buses + %s) * 10)
                            WHERE date = %s
                        """, (len(bus_ids), len(bus_ids), target_date))
                        
                        conn.commit()
                        log_queue.put(f"[{time.time()}] ✅ 2 New buses activated and 20 seats added to pool.")
            
        except mysql.connector.Error as err:
            conn.rollback()
            log_queue.put(f"[{time.time()}] ❌ Auto-Scaler Error: {err}")
            
        time.sleep(3)
        
    cursor.close()
    conn.close()

def admin_merge_buses(target_date, stop_event):
    """Background daemon simulating an Admin merging buses when load <= 0.2 (Req 7, 8)."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    while not stop_event.is_set():
        try:
            cursor.execute("SELECT load_factor, active_buses FROM DailyMetrics WHERE date = %s", (target_date,))
            row = cursor.fetchone()
            
            if row and row[0] <= 0.20 and row[1] > 1:
                log_queue.put(f"[{time.time()}] 📉 LOAD LOW ({row[0]}). Admin initiating bus merge...")
                
                cursor.execute("""
                    SELECT daily_bus_id, group_id FROM DailyBus 
                    WHERE date = %s AND status = 'ACTIVE' 
                    LIMIT 2
                """, (target_date,))
                
                buses = cursor.fetchall()
                if len(buses) == 2:
                    bus1_id, group1_id = buses[0]
                    bus2_id, group2_id = buses[1]
                    
                    cursor.execute("""
                        UPDATE DailyBusGroup SET status = 'ALTERATION_IN_PROCESS' 
                        WHERE group_id IN (%s, %s)
                    """, (group1_id, group2_id))
                    conn.commit()
                    log_queue.put(f"[{time.time()}] ⚠️ UI ALERT: 'Bus alteration in process' (Seats hidden).")
                    
                    time.sleep(2)
                    
                    cursor.execute("""
                        UPDATE DailyBus SET group_id = %s, status = 'INACTIVE' 
                        WHERE daily_bus_id = %s
                    """, (group1_id, bus2_id))
                    
                    cursor.execute("""
                        UPDATE DailyBusGroup SET status = 'NORMAL' WHERE group_id = %s
                    """, (group1_id,))
                    
                    cursor.execute("""
                        UPDATE DailyMetrics SET active_buses = active_buses - 1 WHERE date = %s
                    """, (target_date,))
                    
                    conn.commit()
                    log_queue.put(f"[{time.time()}] ✅ Merge complete. Redundant bus deactivated. UI Alert cleared.")
                    
        except mysql.connector.Error as err:
            conn.rollback()
            log_queue.put(f"[{time.time()}] ❌ Admin Merge Error: {err}")
            
        time.sleep(5)
        
    cursor.close()
    conn.close()

def simulate_client_booking(client_id, target_date):
    """Simulates a single client attempting to lock and book a seat (Req 3, 9, 12)."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
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
            log_queue.put(f"[{time.time()}] Client {client_id[-4:]}: No available seats found.")
            return False
            
        seat_id, daily_bus_id = row
        
        cursor.execute("""
            UPDATE SeatAvailability 
            SET status = 'LOCKED', locked_by = %s, lock_expires_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE)
            WHERE seat_id = %s
        """, (client_id, seat_id))
        conn.commit()
        
        log_queue.put(f"[{time.time()}] Client {client_id[-4:]}: LOCKED seat {seat_id[-4:]} for 5 minutes.")
        
        time.sleep(1)
        
        booking_id = str(uuid.uuid4())
        
        cursor.execute("""
            INSERT INTO Booking (booking_id, user_id, seat_id, booking_date, status)
            VALUES (%s, %s, %s, %s, 'CONFIRMED')
        """, (booking_id, client_id, seat_id, target_date))
        
        cursor.execute("UPDATE SeatAvailability SET status = 'BOOKED' WHERE seat_id = %s", (seat_id,))
        
        cursor.execute("""
            UPDATE DailyMetrics 
            SET booked_seats = booked_seats + 1, 
                load_factor = (booked_seats + 1) / (active_buses * 10)
            WHERE date = %s
        """, (target_date,))
        
        conn.commit()
        log_queue.put(f"[{time.time()}] Client {client_id[-4:]}: ✅ SUCCESSFULLY BOOKED seat {seat_id[-4:]}.")
        return True
        
    except mysql.connector.Error as err:
        log_queue.put(f"[{time.time()}] Client {client_id[-4:]}: ❌ Database Error: {err}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def simulate_client_cancellation(target_date):
    """Simulates a random client cancelling their ticket (Req 6)."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT booking_id, seat_id, user_id 
            FROM Booking 
            WHERE booking_date = %s AND status = 'CONFIRMED'
            ORDER BY RAND() LIMIT 1
            FOR UPDATE SKIP LOCKED
        """, (target_date,))
        
        row = cursor.fetchone()
        if not row:
            return False
            
        booking_id, seat_id, user_id = row
        
        cursor.execute("UPDATE Booking SET status = 'CANCELLED' WHERE booking_id = %s", (booking_id,))
        
        cursor.execute("""
            UPDATE SeatAvailability 
            SET status = 'AVAILABLE', locked_by = NULL, lock_expires_at = NULL 
            WHERE seat_id = %s
        """, (seat_id,))

        cursor.execute("""
            UPDATE DailyMetrics 
            SET booked_seats = booked_seats - 1, 
                load_factor = (booked_seats - 1) / (active_buses * 10)
            WHERE date = %s
        """, (target_date,))
        
        conn.commit()
        log_queue.put(f"[{time.time()}] ↩️ Client {user_id[-4:]} CANCELLED booking for seat {seat_id[-4:]}.")
        return True
        
    except mysql.connector.Error as err:
        conn.rollback()
        log_queue.put(f"[{time.time()}] ❌ Cancellation Error: {err}")
        return False
    finally:
        cursor.close()
        conn.close()

def run_simulation(num_clients):
    print("--- Starting Concurrency Simulation ---")
    print("Logs are being written asynchronously to 'archive_activity.log'...")
    target_date = date.today()
    
    clients = [str(uuid.uuid4()) for _ in range(num_clients)]
    
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT IGNORE INTO Users (user_id, role, username) VALUES (%s, 'VISITOR', %s)",
        [(c_id, f"sim_user_{c_id[-4:]}") for c_id in clients]
    )
    
    # Update DailyMetrics visitor count
    cursor.execute("""
        UPDATE DailyMetrics SET visitor_count = visitor_count + %s WHERE date = %s
    """, (num_clients, target_date))
    conn.commit()
    conn.close()

    stop_event = threading.Event()

    monitor_thread = threading.Thread(target=monitor_resources, args=(stop_event,))
    logger_thread = threading.Thread(target=async_logger, args=(stop_event,))
    scaler_thread = threading.Thread(target=auto_scale_buses, args=(target_date, stop_event,))
    admin_thread = threading.Thread(target=admin_merge_buses, args=(target_date, stop_event,))

    monitor_thread.start()
    logger_thread.start()
    scaler_thread.start()
    admin_thread.start()

    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = []
        for c_id in clients:
            futures.append(executor.submit(simulate_client_booking, c_id, target_date))
            
            if random.random() < 0.10:
                futures.append(executor.submit(simulate_client_cancellation, target_date))
                
        for future in futures:
            future.result()
            
    execution_time = time.time() - start_time

    stop_event.set()
    monitor_thread.join()
    logger_thread.join()
    scaler_thread.join()
    admin_thread.join()

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