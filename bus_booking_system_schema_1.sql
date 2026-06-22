CREATE DATABASE IF NOT EXISTS bus_booking_system;
USE bus_booking_system;

-- 1. Create Visitor Table
CREATE TABLE Visitor (
    id INT AUTO_INCREMENT PRIMARY KEY
) ENGINE=InnoDB;

-- 1.1 Create Admin Table for secure admin login
CREATE TABLE Admin (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    salt VARCHAR(50) NOT NULL
) ENGINE=InnoDB;

-- 2. Create Bus Table
CREATE TABLE Bus (
    id INT AUTO_INCREMENT PRIMARY KEY,
    total_seats INT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
) ENGINE=InnoDB;

-- 3. Create Seat Table
CREATE TABLE Seat (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bus_id INT,
    seat_number VARCHAR(10),
    FOREIGN KEY (bus_id) REFERENCES Bus(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 4. Create Trip Table
CREATE TABLE Trip (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bus_id INT,
    trip_date DATETIME NOT NULL,
    system_status ENUM('Active', 'Merging') DEFAULT 'Active',
    FOREIGN KEY (bus_id) REFERENCES Bus(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- 5. Create Booking Table
CREATE TABLE Booking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    visitor_id INT,
    trip_id INT,
    seat_id INT,
    booking_status ENUM('Pending', 'Booked', 'Cancelled') NOT NULL,
    lock_expires_at DATETIME NULL,
    FOREIGN KEY (visitor_id) REFERENCES Visitor(id),
    FOREIGN KEY (trip_id) REFERENCES Trip(id),
    FOREIGN KEY (seat_id) REFERENCES Seat(id)
) ENGINE=InnoDB;

-- Create Indexes to speed up concurrency checks
CREATE INDEX idx_booking_status ON Booking(booking_status, lock_expires_at);
CREATE INDEX idx_trip_seat ON Booking(trip_id, seat_id);

-- 1. Insert Anonymous Visitors
-- Using DEFAULT tells MySQL to just increment the ID automatically
INSERT INTO Visitor (id) VALUES 
(DEFAULT), 
(DEFAULT), 
(DEFAULT);

-- 1.2 Insert default admin user
INSERT INTO Admin (username, password_hash, salt) VALUES
('admin', '3bf643e045c87c659fb9172b44b1e9ba075d9060328b22a717fea227280f4139', 'bus-booking-salt');

-- 2. Insert 2 Dummy Buses (10 seats each)
INSERT INTO Bus (total_seats, is_active) VALUES
(10, TRUE),
(10, TRUE);

-- 3. Insert Seats for Bus 1 (IDs 1-10)
INSERT INTO Seat (bus_id, seat_number) VALUES
(1, '1'),
(1, '2'),
(1, '3'),
(1, '4'),
(1, '5'),
(1, '6'),
(1, '7'),
(1, '8'),
(1, '9'),
(1, '10');

-- 4. Insert Seats for Bus 2 (IDs 11-20)
INSERT INTO Seat (bus_id, seat_number) VALUES
(2, '1'),
(2, '2'),
(2, '3'),
(2, '4'),
(2, '5'),
(2, '6'),
(2, '7'),
(2, '8'),
(2, '9'),
(2, '10');

-- 5. Insert Trips for multiple days
-- Note: Updated column name to your 'trip_date'
INSERT INTO Trip (bus_id, trip_date, system_status) VALUES
(1, '2026-07-01 08:00:00', 'Active'), -- Trip 1
(1, '2026-07-02 08:00:00', 'Active'), -- Trip 2
(2, '2026-07-01 10:00:00', 'Active'); -- Trip 3

-- 6. Insert Bookings
-- Insert a fully booked ticket (Visitor 1 booked Seat 1 on Trip 1)
INSERT INTO Booking (visitor_id, trip_id, seat_id, booking_status, lock_expires_at) VALUES
(1, 1, 1, 'Booked', NULL);

-- Insert a pending ticket (Visitor 2 is holding Seat 2 on Trip 1)
-- Notice we set the lock_expires_at time to 5 minutes into the future
INSERT INTO Booking (visitor_id, trip_id, seat_id, booking_status, lock_expires_at) VALUES
(2, 1, 2, 'Pending', DATE_ADD(NOW(), INTERVAL 5 MINUTE));

SHOW TABLES;

SELECT 
    b.id AS booking_id,
    v.id AS visitor_id,
    t.trip_date,
    s.seat_number,
    b.booking_status,
    b.lock_expires_at
FROM Booking b
JOIN Visitor v ON b.visitor_id = v.id
JOIN Trip t ON b.trip_id = t.id
JOIN Seat s ON b.seat_id = s.id;

SELECT * FROM Booking;