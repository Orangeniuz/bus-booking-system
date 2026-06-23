import mysql.connector
import uuid
import time
import threading
import psutil
import multiprocessing
import random
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from datetime import date, timedelta

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'your_new_password',
    'database': 'bus_booking_system',
    'ssl_disabled': True
}

def monitor_resources(stop_event, metrics_dict):
    """Background thread to monitor CPU and Memory usage."""
    process = psutil.Process()
    metrics_dict["start_idle_time"] = psutil.cpu_times().idle
    
    while not stop_event.is_set():
        metrics_dict["max_cpu"] = max(metrics_dict["max_cpu"], psutil.cpu_percent(interval=0.1))
        metrics_dict["max_virt_mem"] = max(metrics_dict["max_virt_mem"], psutil.virtual_memory().used)
        metrics_dict["max_phys_mem"] = max(metrics_dict["max_phys_mem"], process.memory_info().rss)
        
    metrics_dict["end_idle_time"] = psutil.cpu_times().idle

def async_logger(stop_event, log_queue, batch_size=50):
    """
    Consumer Thread: Reads from queue and writes to disk in batches.
    
    REQUIREMENT 14 (Disk Activity Documentation):
    - Activity: Multiple simulation threads generate log messages asynchronously. 
      Instead of each thread competing for disk access, they push messages to an 
      in-memory Queue. This thread consumes that Queue and writes to 'archive_activity.log'.
    - Impact on Performance: This INCREASES overall performance. By offloading I/O 
      to a dedicated background thread, the active simulation threads never block 
      waiting for the physical disk to spin or the OS file handle to free up.
      
    REQUIREMENT 15 (Proving the Method):
    - This implements the 'Asynchronous Batch Logging' pattern.
    - Why it is optimized: The `batch_size=50` parameter caches messages and writes 
      them in a single block operation. HDDs and SSDs handle continuous block writes 
      significantly faster than fragmented, rapid micro-writes. This minimizes 
      kernel-level context switching and prevents disk I/O bottlenecks during high 
      concurrency bursts.
    """
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
            except multiprocessing.queues.Empty:
                # Using multiprocessing Empty exception
                pass
            except Exception:
                # Catch standard queue.Empty if running in a mode that uses standard queue
                pass

        if buffer:
            log_file.write("\n".join(buffer) + "\n")
            log_file.flush()

def auto_scale_buses(valid_dates, stop_event, log_queue):
    """Background daemon tracking load factor to activate extra buses."""
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    while not stop_event.is_set():
        for target_date in valid_dates:
            try:
                cursor.execute("SELECT load_factor, active_buses FROM DailyMetrics WHERE date = %s", (target_date,))
                row = cursor.fetchone()
                
                if row:
                    load_factor, active_buses = row
                    
                    if load_factor >= 0.8 and active_buses < 100:
                        log_queue.put(f"[{time.time()}] ⚠️ LOAD HIGH on {target_date} ({load_factor}). Activating 2 new buses...")
                        
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
                            log_queue.put(f"[{time.time()}] ✅ 2 New buses activated on {target_date}.")
                
            except mysql.connector.Error as err:
                conn.rollback()
                log_queue.put(f"[{time.time()}] ❌ Auto-Scaler Error: {err}")
                
        time.sleep(3)
        
    cursor.close()
    conn.close()

def lock_sweeper(stop_event, log_queue):
    """
    Background daemon to release abandoned seat locks.
    Scans the database periodically and resets seats where the lock has expired.
    """
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    while not stop_event.is_set():
        try:
            cursor.execute("""
                UPDATE SeatAvailability 
                SET status = 'AVAILABLE', locked_by = NULL, lock_expires_at = NULL
                WHERE status = 'LOCKED' AND lock_expires_at < NOW()
            """)
            
            if cursor.rowcount > 0:
                conn.commit()
                log_queue.put(f"[{time.time()}] 🧹 Sweeper: Reclaimed {cursor.rowcount} expired seat locks.")
                
        except mysql.connector.Error as err:
            conn.rollback()
            log_queue.put(f"[{time.time()}] ❌ Sweeper Error: {err}")
            
        time.sleep(10)  # Check every 10 seconds
        
    cursor.close()
    conn.close()

def admin_login(username, log_queue):
    """Simulates an admin user logging in."""
    log_queue.put(f"[{time.time()}] User '{username}' attempting login...")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, role FROM Users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if user and user[1] == 'ADMIN':
            log_queue.put(f"[{time.time()}] 🔓 Admin login successful for '{username}'.")
            return user[0]
        else:
            log_queue.put(f"[{time.time()}] ⛔ Login failed or insufficient permissions.")
            return None
    except mysql.connector.Error as err:
        log_queue.put(f"[{time.time()}] DB Error during login: {err}")
        return None
    finally:
        cursor.close()
        conn.close()

def trigger_manual_merge(admin_id, target_date, log_queue):
    """Admin manually triggers a bus merge for a specific date if conditions allow."""
    if not admin_id:
        log_queue.put(f"[{time.time()}] ❌ Unauthorized: Admin ID required to perform merge.")
        return False

    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT load_factor, active_buses FROM DailyMetrics WHERE date = %s", (target_date,))
        row = cursor.fetchone()
        
        if row and row[0] <= 0.20 and row[1] > 1:
            log_queue.put(f"[{time.time()}] 📉 Admin {admin_id[-4:]} initiated bus merge on {target_date} (Load: {row[0]}).")
            
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
                log_queue.put(f"[{time.time()}] ✅ Merge complete on {target_date}. Redundant bus deactivated.")
                return True
        else:
            log_queue.put(f"[{time.time()}] ⛔ Merge aborted: Load factor too high or insufficient buses.")
            return False
            
    except mysql.connector.Error as err:
        conn.rollback()
        log_queue.put(f"[{time.time()}] ❌ Admin Merge Error: {err}")
        return False
    finally:
        cursor.close()
        conn.close()

def simulate_client_booking(client_id, target_date, log_queue):
    """Simulates a single client attempting to lock and book a seat."""
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
            log_queue.put(f"[{time.time()}] Client {client_id[-4:]}: No available seats found for {target_date}.")
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
        log_queue.put(f"[{time.time()}] Client {client_id[-4:]}: ✅ SUCCESSFULLY BOOKED seat {seat_id[-4:]} on {target_date}.")
        return True
        
    except mysql.connector.Error as err:
        log_queue.put(f"[{time.time()}] Client {client_id[-4:]}: ❌ Database Error: {err}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def simulate_client_cancellation(target_date, log_queue):
    """Simulates a random client cancelling their ticket."""
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

def run_simulation(num_clients, mode='threading'):
    """
    Runs the simulation using one of three modes: 'iterative', 'threading', or 'forking'.
    """
    print(f"--- Starting Concurrency Simulation [{mode.upper()} MODE] ---")
    print("Logs are being written asynchronously to 'archive_activity.log'...")
    
    # Use Multiprocessing Manager to create safe shared objects across processes/threads
    manager = multiprocessing.Manager()
    log_queue = manager.Queue()
    metrics_dict = manager.dict({
        "max_cpu": 0.0,
        "max_virt_mem": 0,
        "max_phys_mem": 0,
        "start_idle_time": 0.0,
        "end_idle_time": 0.0
    })

    valid_dates = [date.today() + timedelta(days=i) for i in range(7)]
    clients = [str(uuid.uuid4()) for _ in range(num_clients)]
    client_assignments = [(c_id, random.choice(valid_dates)) for c_id in clients]
    
    # Database Initialization Phase
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT IGNORE INTO Users (user_id, role, username) VALUES (%s, 'VISITOR', %s)",
        [(c_id, f"sim_user_{c_id[-4:]}") for c_id in clients]
    )
    for _, target_date in client_assignments:
        cursor.execute("UPDATE DailyMetrics SET visitor_count = visitor_count + 1 WHERE date = %s", (target_date,))
    conn.commit()
    conn.close()

    # Start Background Daemons (These remain as threads inside the main process)
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=monitor_resources, args=(stop_event, metrics_dict))
    logger_thread = threading.Thread(target=async_logger, args=(stop_event, log_queue))
    scaler_thread = threading.Thread(target=auto_scale_buses, args=(valid_dates, stop_event, log_queue))
    sweeper_thread = threading.Thread(target=lock_sweeper, args=(stop_event, log_queue))

    monitor_thread.start()
    logger_thread.start()
    scaler_thread.start()
    sweeper_thread.start()

    start_time = time.time()
    
    # =========================================================
    # REQUIREMENT 10: EXECUTION MODES
    # =========================================================
    
    if mode == 'iterative':
        # Approach 10a: Iterative Serving (Sequential Execution)
        for c_id, target_date in client_assignments:
            simulate_client_booking(c_id, target_date, log_queue)
            if random.random() < 0.10:
                simulate_client_cancellation(target_date, log_queue)
                
    elif mode == 'threading':
        # Approach 10b: Threading Techniques (Shared Memory Space)
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = []
            for c_id, target_date in client_assignments:
                futures.append(executor.submit(simulate_client_booking, c_id, target_date, log_queue))
                if random.random() < 0.10:
                    futures.append(executor.submit(simulate_client_cancellation, target_date, log_queue))
            for future in futures:
                future.result()
                
    elif mode == 'forking':
        # Approach 10c: Forking Techniques (Distinct OS Processes)
        with ProcessPoolExecutor(max_workers=10) as executor:
            futures = []
            for c_id, target_date in client_assignments:
                futures.append(executor.submit(simulate_client_booking, c_id, target_date, log_queue))
                if random.random() < 0.10:
                    futures.append(executor.submit(simulate_client_cancellation, target_date, log_queue))
            for future in futures:
                future.result()
    
    else:
        print("Invalid mode selected.")

    execution_time = time.time() - start_time
    
    # Simulate Manual Admin Merge
    print("\n--- Simulating Manual Admin Action ---")
    admin_id = admin_login('admin_super', log_queue)
    if admin_id:
        trigger_manual_merge(admin_id, date.today() + timedelta(days=6), log_queue)

    # Teardown
    stop_event.set()
    monitor_thread.join()
    logger_thread.join()
    scaler_thread.join()
    sweeper_thread.join()

    cpu_idle_diff = metrics_dict["end_idle_time"] - metrics_dict["start_idle_time"]
    
    print("\n--- Simulation Complete ---")
    print(f"Total Execution Time : {execution_time:.2f} seconds")
    print(f"Total Clients Served : {num_clients}")
    print("\n--- System Resource Metrics ---")
    print(f"Maximum CPU Usage    : {metrics_dict['max_cpu']}%")
    print(f"CPU Idle Time Passed : {cpu_idle_diff:.2f} seconds")
    print(f"Max Virtual Memory   : {metrics_dict['max_virt_mem'] / (1024 * 1024):.2f} MB")
    print(f"Max Physical Memory  : {metrics_dict['max_phys_mem'] / (1024 * 1024):.2f} MB")

if __name__ == "__main__":
    # You can change 'mode' to 'iterative', 'threading', or 'forking'
    run_simulation(num_clients=120, mode='threading')