from async_logger import AsyncBatchLogger
import os
import threading
import time
from booking_engine import request_seat, admin_merge_trips

# 1. Thread-Safe Visitor Counter
class VisitorCounter:
    """
    Keeps track of active visitors currently being processed by the server.
    Uses a memory lock to prevent race conditions during counting.
    """
    def __init__(self):
        self.active_count = 0
        self.lock = threading.Lock() # Application-level lock

    def increment(self):
        with self.lock:
            self.active_count += 1
            return self.active_count

    def decrement(self):
        with self.lock:
            self.active_count -= 1
            return self.active_count


# 2. The Client Handler
def handle_client(visitor_id, trip_id, seat_id, counter=None, logger=None):
    """
    Handles a single client request.
    If logger is provided, logs are batched asynchronously.
    If counter is provided, the active visitor count is updated.
    """
    def log(message):
        if logger is not None:
            logger.log(message)
        else:
            prefix = f"[PID {os.getpid()}] " if os.name != 'nt' else ''
            print(prefix + message)

    if counter is not None:
        current_visitors = counter.increment()
        log(f"Visitor {visitor_id} connected. (Active: {current_visitors})")
    else:
        log(f"Visitor {visitor_id} connected.")

    log(f"Visitor {visitor_id} attempting to book Seat {seat_id} on Trip {trip_id}...")
    time.sleep(0.5)

    success = request_seat(visitor_id, trip_id, seat_id)

    if success:
        log(f"[SUCCESS] Visitor {visitor_id} locked the seat!")
    else:
        log(f"[FAIL] Visitor {visitor_id} failed to get the seat.")

    if counter is not None:
        current_visitors = counter.decrement()
        log(f"Visitor {visitor_id} disconnected. (Active: {current_visitors})")
    else:
        log(f"Visitor {visitor_id} disconnected.")

# 3. Threading Server Approach (Parallel)
def run_threading_server(client_requests, counter, logger):
    print("\n" + "="*50)
    print("STARTING THREADING SERVER")
    print("Notice how all visitors connect simultaneously.")
    print("Your MySQL FOR UPDATE locks will decide who wins the seat!")
    print("="*50)
    
    start_time = time.time()
    threads = []
    
    for req in client_requests:
        # Create a new thread for each client request
        t = threading.Thread(
            target=handle_client, 
            args=(req['visitor_id'], req['trip_id'], req['seat_id'], counter, logger)
        )
        threads.append(t)
        t.start() # Starts the thread without blocking the loop
        
    # Wait for all threads to finish before moving on
    for t in threads:
        t.join()
        
    duration = time.time() - start_time
    print(f"\n[Threading Server Finished in {duration:.2f} seconds]")


def run_iterative_server(client_requests, counter, logger):
    print("\n" + "="*50)
    print("STARTING ITERATIVE SERVER")
    print("Visitors are handled one by one. There is no concurrency.")
    print("This means only one connection is active at a time.")
    print("="*50)

    start_time = time.time()
    for req in client_requests:
        handle_client(req['visitor_id'], req['trip_id'], req['seat_id'], counter, logger)

    duration = time.time() - start_time
    print(f"\n[Iterative Server Finished in {duration:.2f} seconds]")


def run_forking_server(client_requests):
    print("\n" + "="*50)
    print("STARTING FORKING SERVER")
    print("Each visitor is handled in a separate child process.")
    print("This demonstrates OS-level process isolation and database locking across forks.")
    print("="*50)

    children = []
    for req in client_requests:
        pid = os.fork()
        if pid == 0:
            handle_client(req['visitor_id'], req['trip_id'], req['seat_id'])
            os._exit(0)
        else:
            children.append(pid)

    for pid in children:
        os.waitpid(pid, 0)

    print("\n[Forking Server Finished. All child processes have exited.]")


# --- Main Execution ---
if __name__ == "__main__":
    counter = VisitorCounter()
    logger = AsyncBatchLogger(filepath="archive.log", batch_size=5) # Initialize Logger

    # We are simulating 3 different visitors trying to book the EXACT SAME SEAT (Seat 4, Trip 1)
    # Visitor 4, 5, and 6 don't exist in our DB yet, but your auto-increment Visitor table doesn't care.
    client_queue = [
        {'visitor_id': 1, 'trip_id': 1, 'seat_id': 4},
        {'visitor_id': 2, 'trip_id': 1, 'seat_id': 4},
        {'visitor_id': 3, 'trip_id': 1, 'seat_id': 4}
    ]

    # Test 1: Iterative server (one-at-a-time)
    run_iterative_server(client_queue, counter, logger)

    # Test 2: Threading server (parallel threads)
    run_threading_server(client_queue, counter, logger)

    # Test 3: Forking server (each request handled by a new process)
    run_forking_server(client_queue)

    # Attempt an admin merge after the demo runs
    print("\nAttempting admin merge with credentials admin/password123...")
    merge_result = admin_merge_trips('admin', 'password123', target_trip_id=1, source_trip_id=3)
    print(f"Admin merge result: {merge_result}")

    # CRITICAL: Tell the logger to flush remaining memory to disk before Python exits
    logger.shutdown()
    print("Server shut down safely. Logs saved.")