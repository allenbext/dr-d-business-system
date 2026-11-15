"""
db.py

This file contains the PostgreSQL connection settings.

Other Python files will use get_connection()
whenever they need to read or write data in the database.
"""

import os

# psycopg allows Python to communicate with PostgreSQL.
import psycopg

# python-dotenv allows us to read settings
# from the .env file.
from dotenv import load_dotenv


# Load the values from the .env file.
# override=True makes Python use the values from the file even when
# Windows already has older environment variables with the same names.
load_dotenv(override=True)


def get_connection():
    """
    Create a connection to the dr_d_business PostgreSQL database.
    """

    return psycopg.connect(

        # PostgreSQL is currently running
        # on our own computer.
        host=os.getenv("DB_HOST"),

        # Default PostgreSQL port.
        port=os.getenv("DB_PORT"),

        # Database we created in DBeaver.
        dbname=os.getenv("DB_NAME"),

        # PostgreSQL user.
        user=os.getenv("DB_USER"),

        # Password is read from .env
        # instead of being written directly in the code.
        password=os.getenv("DB_PASSWORD")
    )