import threading
import time
import random
import concurrent.futures
from booking_engine import request_seat
from async_logger import AsyncBatchLogger
from server_simulation import VisitorCounter

def agent_worker(agent_id, counter, logger):
    """
    Simulates a single autonomous agent browsing the site and trying to book a random seat.
    """
    # 1. Simulate the agent taking time to "click around" the website (0.1 to 1.5 seconds)
    time.sleep(random.uniform(0.1, 1.5))
    
    current_active = counter.increment()
    
    # 2. Pick a random configuration
    # Assuming we have Visitors 1-5, Trips 1-3, and Seats 1-8 seeded in the DB
    visitor_id = random.randint(1, 5)
    trip_id = random.randint(1, 3)
    seat_id = random.randint(1, 8)
    
    logger.log(f"[Agent {agent_id}] Online (Active: {current_active}). V:{visitor_id} wants Trip {trip_id}, Seat {seat_id}.")
    
    # 3. Attempt the booking
    success = request_seat(visitor_id, trip_id, seat_id)
    
    # 4. Log the result
    if success:
        logger.log(f"[Agent {agent_id}] SUCCESS! Secured Seat {seat_id} on Trip {trip_id}.")
    else:
        logger.log(f"[Agent {agent_id}] FAILED. Seat {seat_id} on Trip {trip_id} was taken.")
        
    counter.decrement()

def run_mass_simulation(total_agents=50):
    """
    Deploys a swarm of agents simultaneously to stress-test the database locks and async logger.
    """
    print("="*50)
    print(f"DEPLOYING {total_agents} AUTONOMOUS AGENTS")
    print("="*50)
    
    counter = VisitorCounter()
    logger = AsyncBatchLogger(filepath="archive.log", batch_size=10)
    
    start_time = time.time()
    
    # ThreadPoolExecutor efficiently manages a massive swarm of threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=total_agents) as executor:
        # We submit all agent tasks to the executor at once
        futures = [
            executor.submit(agent_worker, i, counter, logger) 
            for i in range(1, total_agents + 1)
        ]
        
        # This waits for all agents to finish their tasks
        concurrent.futures.wait(futures)
        
    duration = time.time() - start_time
    logger.shutdown()
    
    print(f"\nSimulation complete in {duration:.2f} seconds.")
    print("Check 'archive.log' to see the chaotic batch-writing in action!")

if __name__ == "__main__":
    # Ensure you have at least 5 Visitors seeded in your database before running this!
    # INSERT INTO Visitor (id) VALUES (DEFAULT), (DEFAULT); -- Run this in MySQL if needed
    run_mass_simulation(total_agents=50)