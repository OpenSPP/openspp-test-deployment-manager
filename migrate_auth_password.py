#!/usr/bin/env python3
# ABOUTME: Migration script to add auth_password field to existing deployments
# ABOUTME: Run this once to update the database schema for authentication support

import sqlite3
import secrets
import string
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_database(db_path: str = "deployments.db"):
    """Add auth_password column and generate passwords for existing deployments"""
    
    # Make sure db_path is absolute
    if not Path(db_path).is_absolute():
        base_dir = Path(__file__).parent
        db_path = str(base_dir / db_path)
    
    logger.info(f"Migrating database at {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(deployments)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'auth_password' in columns:
            logger.info("auth_password column already exists, skipping migration")
            return
        
        # Add the auth_password column
        logger.info("Adding auth_password column to deployments table")
        cursor.execute("ALTER TABLE deployments ADD COLUMN auth_password TEXT DEFAULT ''")
        
        # Generate passwords for existing deployments
        cursor.execute("SELECT id FROM deployments")
        deployments = cursor.fetchall()
        
        alphabet = string.ascii_letters + string.digits
        for (deployment_id,) in deployments:
            # Generate a random 16-character password
            password = ''.join(secrets.choice(alphabet) for _ in range(16))
            cursor.execute(
                "UPDATE deployments SET auth_password = ? WHERE id = ?",
                (password, deployment_id)
            )
            logger.info(f"Generated password for deployment {deployment_id}")
        
        conn.commit()
        logger.info(f"Migration completed successfully. Updated {len(deployments)} deployments.")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()