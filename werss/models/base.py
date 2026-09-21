# Maintained by SONGJUNSONG — Jilin Business and Technology College, School of Finance and Economics
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Text, BigInteger

Base = declarative_base()


class DataStatus:
    DELETED: int = 1000
    ACTIVE: int = 1
    INACTIVE: int = 2
    PENDING: int = 3
    COMPLETED: int = 4
    FAILED: int = 5
    FETCHING: int = 6


DATA_STATUS = DataStatus()
