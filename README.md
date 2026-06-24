Design a bus ticket booking software:

1) Show the number of visitors for this bus booking software.

2) Have starting limit on number of buses. (e.g. 10)

3) Multiple clients should be able to book the bus simultaneously but not the same seat. There should be waiting time (e.g. 5 minutes) indicated to allow one client to process same seat on the bus. If the client does not process anything after selecting the seat after the waiting time expires, this seat could be allowed for processing by the next client.

4) When the load factor reaches maximum threshold (e.g. 0.8, which means 80% of seats from all buses are booked), then there could be some extra buses allowed (e.g. 2) until final limit (e.g. 100 buses) is reached.

5) Allow the booking for multiple days now.

6) Allow tickets cancellation for the clients.

7) Now have an admin login for this application, which could allow merging of the buses if the load factor is below minimum threshold (e.g. 0.2), given the fact the buses seats do not collide.

8) During merging of the buses, client should not be able to view seats of the buses. But the bus should be shown with a alert indicating "Bus alteration in process".

9) Now simulate this same process using multiple agent booking using parallel clients.

10) More than one client could be served using these approaches:
 a) Iterative serving.
 b) Threading techniques.
 c) Forking techniques.

11) Find the idle time of CPU, maximum CPU usage and maximum virtual and physical memory used by this software.

12) Use lock at suitable locations to carry on smooth concurrency in programming.

13) Write logs of above activity as "archive". Multiple threads should write in the same file.

14) Document the disk activities while writing archive. Is this file write reducing/increasing the overall performance.

15) Try to bring improvements in disk I/O activity or prove your method of writing is best approach to handle disk I/O stuff.
