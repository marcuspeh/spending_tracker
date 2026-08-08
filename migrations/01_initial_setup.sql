-- 01_initial_setup.sql
-- Creates the four core tables produced by Tortoise.generate_schemas().
-- Apply this against a fresh database; for an existing one use the
-- targeted ALTER migrations in 02 and 03 instead.

CREATE TABLE users (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    telegram_chat_id INT NOT NULL,
    telegram_username VARCHAR(255) NULL,
    name VARCHAR(255) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                 ON UPDATE CURRENT_TIMESTAMP(6),
    deleted_at DATETIME(6) NULL,
    UNIQUE KEY uniq_users_telegram_chat_id (telegram_chat_id)
);

CREATE TABLE user_emails (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    email VARCHAR(320) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                 ON UPDATE CURRENT_TIMESTAMP(6),
    deleted_at DATETIME(6) NULL,
    UNIQUE KEY uniq_user_emails_email (email)
);

CREATE TABLE imported_emails (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    message_id VARCHAR(191) NOT NULL,
    status VARCHAR(16) NOT NULL,
    reason VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uniq_imported_emails_message_id (message_id)
);

CREATE TABLE transactions (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    merchant VARCHAR(255) NOT NULL,
    payment_method VARCHAR(32) NOT NULL,
    description TEXT NULL,
    transaction_time DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                 ON UPDATE CURRENT_TIMESTAMP(6),
    deleted_at DATETIME(6) NULL,
    KEY idx_transactions_user_time (user_id, transaction_time),
    KEY idx_transactions_user_deleted (user_id, deleted_at)
);
