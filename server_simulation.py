from async_logger import AsyncBatchLogger
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
def handle_client(visitor_id, trip_id, seat_id, counter, logger): # Added logger parameter
    current_visitors = counter.increment()
    
    # Replace standard prints with logger.log
    logger.log(f"Visitor {visitor_id} connected. (Active: {current_visitors})")
    logger.log(f"Visitor {visitor_id} attempting to book Seat {seat_id} on Trip {trip_id}...")
    
    time.sleep(0.5) 
    
    success = request_seat(visitor_id, trip_id, seat_id)
    
    if success:
        logger.log(f"[SUCCESS] Visitor {visitor_id} locked the seat!")
    else:
        logger.log(f"[FAIL] Visitor {visitor_id} failed to get the seat.")

    current_visitors = counter.decrement()
    logger.log(f"Visitor {visitor_id} disconnected. (Active: {current_visitors})")

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

    # Test 1: Threading
    # In this test, it is a race. The active visitor count will hit 3 simultaneously.
    # MySQL will force two of them to wait, and only one will succeed.
    run_threading_server(client_queue, counter, logger)

    # Pass the logger to the threading server
    print("\nStarting Threading Server... Check archive.log for outputs!")
    threads = []
    for req in client_queue:
        t = threading.Thread(
            target=handle_client, 
            args=(req['visitor_id'], req['trip_id'], req['seat_id'], counter, logger)
        )
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()

    # Attempt an admin merge after the client threads have run
    print("\nAttempting admin merge with credentials admin/password123...")
    merge_result = admin_merge_trips('admin', 'password123', target_trip_id=1, source_trip_id=3)
    print(f"Admin merge result: {merge_result}")

    # CRITICAL: Tell the logger to flush remaining memory to disk before Python exits
    logger.shutdown()
    print("Server shut down safely. Logs saved.")