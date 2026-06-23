CREATE DATABASE IF NOT EXISTS bus_booking_system;
USE bus_booking_system;

-- 1. Create Users Table (Parent)
CREATE TABLE Users (
    user_id CHAR(36) PRIMARY KEY, -- Using CHAR(36) to store UUIDs
    role ENUM('VISITOR', 'ADMIN') NOT NULL,
    username VARCHAR(255) NOT NULL UNIQUE,
    is_active_today BOOLEAN DEFAULT FALSE
);

-- 2. Create Bus Table (Parent)
CREATE TABLE Bus (
    bus_sn INT PRIMARY KEY,       -- Serial Numbers 1 to 100
    capacity INT DEFAULT 10
);

-- 3. Create DailyBusGroup Table (Parent for grouping/merging)
CREATE TABLE DailyBusGroup (
    group_id CHAR(36) PRIMARY KEY,
    date DATE NOT NULL,
    status ENUM('NORMAL', 'ALTERATION_IN_PROCESS') DEFAULT 'NORMAL'
);

-- 4. Create DailyBus Table (Child to Bus and DailyBusGroup)
CREATE TABLE DailyBus (
    daily_bus_id CHAR(36) PRIMARY KEY,
    date DATE NOT NULL,
    bus_sn INT NOT NULL,
    group_id CHAR(36) NOT NULL,
    status ENUM('ACTIVE', 'INACTIVE') NOT NULL,
    FOREIGN KEY (bus_sn) REFERENCES Bus(bus_sn) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES DailyBusGroup(group_id) ON DELETE CASCADE
);

-- 5. Create SeatAvailability Table (Child to DailyBus and Users)
CREATE TABLE SeatAvailability (
    seat_id CHAR(36) PRIMARY KEY,
    daily_bus_id CHAR(36) NOT NULL,
    seat_number INT NOT NULL CHECK (seat_number BETWEEN 1 AND 10),
    status ENUM('AVAILABLE', 'LOCKED', 'BOOKED') DEFAULT 'AVAILABLE',
    locked_by CHAR(36) NULL,      -- Can be NULL if not locked
    lock_expires_at TIMESTAMP NULL,
    FOREIGN KEY (daily_bus_id) REFERENCES DailyBus(daily_bus_id) ON DELETE CASCADE,
    FOREIGN KEY (locked_by) REFERENCES Users(user_id) ON DELETE SET NULL
);

-- 6. Create Booking Table (Child to Users and SeatAvailability)
CREATE TABLE Booking (
    booking_id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    seat_id CHAR(36) NOT NULL UNIQUE, -- A specific seat can only be tied to one booking
    booking_date DATE NOT NULL,
    status ENUM('CONFIRMED', 'CANCELLED') DEFAULT 'CONFIRMED',
    FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (seat_id) REFERENCES SeatAvailability(seat_id) ON DELETE CASCADE
);

-- 7. Create DailyMetrics Table (Standalone Aggregation)
CREATE TABLE DailyMetrics (
    date DATE PRIMARY KEY,
    visitor_count INT DEFAULT 0,
    active_buses INT DEFAULT 10,
    booked_seats INT DEFAULT 0,
    load_factor DECIMAL(5,2) DEFAULT 0.00
);