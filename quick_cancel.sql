-- Quick SQL to cancel a specific ride
-- Run this with: psql -U <your_db_user> -d jk_taxi -f quick_cancel.sql

-- Replace the ride ID below with the one you want to cancel
UPDATE rides_enhanced
SET
    status = 'cancelled',
    driver_id = NULL,
    cancellation_reason = 'Manual cancellation - Admin',
    updated_at = NOW()
WHERE id = 'f64aa3f8-7ba1-489c-9247-5b69ebe7067d';

-- Verify the update
SELECT
    id,
    status,
    driver_id,
    cancellation_reason,
    pickup_location,
    updated_at
FROM rides_enhanced
WHERE id = 'f64aa3f8-7ba1-489c-9247-5b69ebe7067d';
