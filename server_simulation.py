import threading
import time
from booking_engine import request_seat

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
def handle_client(visitor_id, trip_id, seat_id, counter):
    """
    Simulates a single client connecting to the server and trying to book a seat.
    """
    current_visitors = counter.increment()
    print(f"\n[+] Visitor {visitor_id} connected. (Active Visitors: {current_visitors})")
    
    print(f"[*] Visitor {visitor_id} is attempting to book Seat {seat_id} on Trip {trip_id}...")
    
    # Simulate slight network delay
    time.sleep(0.5) 
    
    # Call the actual database function we wrote in booking_engine.py
    success = request_seat(visitor_id, trip_id, seat_id)
    
    if success:
        print(f"[SUCCESS] Visitor {visitor_id} successfully locked the seat!")
    else:
        print(f"[FAIL] Visitor {visitor_id} failed to get the seat. It was taken.")

    current_visitors = counter.decrement()
    print(f"[-] Visitor {visitor_id} disconnected. (Active Visitors: {current_visitors})")


# 3. Threading Server Approach (Parallel)
def run_threading_server(client_requests, counter):
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
            args=(req['visitor_id'], req['trip_id'], req['seat_id'], counter)
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
    run_threading_server(client_queue, counter)