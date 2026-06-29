## 🚀 Features & Requirements Implementation

Design a bus ticket booking software:

**1) Show the number of visitors for this bus booking software.**
*   **Implementation:** The system tracks and displays the current number of active visitors on the main schedule dashboard.

**2) Have starting limit on number of buses. (e.g. 10)**
*   **Implementation:** The database initialization script (`seeding.py`) configures the system to start with exactly 10 active buses out of a physical limit of 100.

**3) Multiple clients should be able to book the bus simultaneously but not the same seat. There should be waiting time (e.g. 5 minutes) indicated to allow one client to process same seat on the bus. If the client does not process anything after selecting the seat after the waiting time expires, this seat could be allowed for processing by the next client.**
*   **Implementation:** Multiple clients can attempt to book simultaneously without race conditions thanks to database row-level locking (`FOR UPDATE SKIP LOCKED`). When a user selects a seat, it receives a 5-minute lock. If the booking isn't completed in time, a background lock sweeper daemon automatically reclaims the seat for the next user.

**4) When the load factor reaches maximum threshold (e.g. 0.8, which means 80% of seats from all buses are booked), then there could be some extra buses allowed (e.g. 2) until final limit (e.g. 100 buses) is reached.**
*   **Implementation:** A background daemon monitors the daily load factor. If booked seats exceed the 80% (0.8) maximum threshold, the system automatically activates 2 additional buses up to the 100-bus limit.

**5) Allow the booking for multiple days now.**
*   **Implementation:** The system supports scheduling and booking for a 7-day rolling window.

**6) Allow tickets cancellation for the clients.**
*   **Implementation:** Clients can view their confirmed bookings on their dashboard and cancel tickets, which immediately frees up the seat.

**7) Now have an admin login for this application, which could allow merging of the buses if the load factor is below minimum threshold (e.g. 0.2), given the fact the buses seats do not collide.**
*   **Implementation:** Admin users have a dedicated login that allows them to manually merge two active buses if the daily load factor drops to 20% (0.2) or below, provided there are no overlapping booked/locked seats between the two buses.

**8) During merging of the buses, client should not be able to view seats of the buses. But the bus should be shown with a alert indicating "Bus alteration in process".**
*   **Implementation:** When a merge is in progress, the targeted bus group status changes to `ALTERATION_IN_PROCESS`. During this state, clients are blocked from viewing seats and shown a "Bus alteration in process" warning alert.

**9) Now simulate this same process using multiple agent booking using parallel clients.**
*   **Implementation:** The `simulation.py` script rigorously tests the system by simulating parallel clients booking and cancelling tickets concurrently across multiple dates.

**10) More than one client could be served using these approaches:**
**a) Iterative serving.**
**b) Threading techniques.**
**c) Forking techniques.**
*   **Implementation:** The simulation script can process client bookings using three different execution models: Iterative serving, Threading (`ThreadPoolExecutor`), and Forking (`ProcessPoolExecutor`).

**11) Find the idle time of CPU, maximum CPU usage and maximum virtual and physical memory used by this software.**
*   **Implementation:** During the simulation, a background thread utilizes the `psutil` library to track and log system performance, outputting the CPU idle time, maximum CPU usage, and maximum virtual and physical memory used.

**12) Use lock at suitable locations to carry on smooth concurrency in programming.**
*   **Implementation:** Concurrency is handled smoothly by applying `FOR UPDATE SKIP LOCKED` during seat selection and cancellation queries, preventing deadlocks and database contention.

**13) Write logs of above activity as "archive". Multiple threads should write in the same file.**
*   **Implementation:** Activity from multiple simulation threads is safely written to a central `archive_activity.log` file.

**14) Document the disk activities while writing archive. Is this file write reducing/increasing the overall performance.**
*   **Implementation:** Extensive code comments in `simulation.py` detail how the system mitigates disk write bottlenecks. By utilizing an in-memory queue and a dedicated background writer thread, the active simulation threads never block waiting for physical disk access, thereby increasing overall system performance.

**15) Try to bring improvements in disk I/O activity or prove your method of writing is best approach to handle disk I/O stuff.**
*   **Implementation:** The project implements an Asynchronous Batch Logging pattern. A built-in benchmarking function proves this method is superior by measuring elapsed time and disk flush counts, showing that caching messages into blocks drastically reduces Kernel context switching compared to synchronous micro-writes.
