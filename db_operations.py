import os
import uuid
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson.objectid import ObjectId
import pandas as pd
from datetime import datetime
import json
import logging
import re
from detector import TOLERANCE_H_MATCH, TOLERANCE_C_MATCH

logger = logging.getLogger(__name__)

MONGO_URI = os.environ.get('MONGO_URI')
DB_NAME = "nmr_database_app"

client = None
db = None
entries_collection = None

def _recursive_clean_for_json(obj):
    """
    Recursively converts ObjectId to string and handles NaN values
    by converting them to None for JSON serialization.
    """
    if isinstance(obj, dict):
        return {k: _recursive_clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_recursive_clean_for_json(elem) for elem in obj]
    elif isinstance(obj, ObjectId):
        return str(obj)
    elif pd.isna(obj): # Check for pandas NaN
        return None
    else:
        return obj

def parse_peaks_string(peaks_str):
    """
    Parses a multiline string of NMR peaks into a list of lists of floats.
    Handles single values and ranges (by taking midpoint).
    """
    peaks = []
    for raw in peaks_str.strip().splitlines():
        parts = raw.strip().split()
        # keep only the first two non-empty tokens
        parts = [p for p in parts if p.strip()]
        if len(parts) != 2:
            continue
        try:
            def _mid(s):
                return (sum(map(float, s.split('-'))) / 2.0) if '-' in s else float(s)
            peaks.append([_mid(parts[0]), _mid(parts[1])])
        except ValueError:
            pass  # silently drop bad lines
    return peaks

def initialize_db_connection():
    """
    Initializes the MongoDB connection and the entries collection.
    This function is designed to be called once at application startup.
    """
    global client, db, entries_collection
    if entries_collection is not None:
        logger.debug("Database connection already initialized.")
        return

    try:
        if MONGO_URI:
            client = MongoClient(MONGO_URI)
            client.admin.command('ping')
            logger.info("Successfully connected to MongoDB Atlas!")
            db = client[DB_NAME]
            entries_collection = db["entries"]
        else:
            logger.warning("MONGO_URI environment variable not set. Attempting local MongoDB fallback.")
            try:
                client = MongoClient('mongodb://localhost:27017/')
                db = client[DB_NAME]
                entries_collection = db["entries"]
                logger.info("Successfully connected to local MongoDB (fallback).")
            except ConnectionFailure as e:
                logger.error(f"Could not connect to local MongoDB: {e}")
                client = None
                db = None
                entries_collection = None
    except ConnectionFailure as e:
        logger.error(f"Could not connect to MongoDB Atlas: {e}")
        client = None
        db = None
        entries_collection = None
    except OperationFailure as e:
        logger.error(f"MongoDB operation failed (authentication/authorization issue?): {e}")
        client = None
        db = None
        entries_collection = None
    except Exception as e:
        logger.exception("An unexpected error occurred during database connection:")
        client = None
        db = None
        entries_collection = None

    logger.info(f"MongoDB connection status: {client is not None}")
    logger.info(f"Database accessible: {db is not None}")
    logger.info(f"Collection initialized: {entries_collection is not None}")

def insert_initial_data_from_json():
    """
    Inserts initial data from 'nmr_database.json' into the database if the collection is empty.
    """
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot insert initial data.")
        return

    if entries_collection.count_documents({}) == 0:
        logger.info("Database is empty. Inserting initial data from nmr_database.json...")
        try:
            script_dir = os.path.dirname(__file__)
            file_path = os.path.join(script_dir, 'nmr_database.json')

            if not os.path.exists(file_path):
                logger.error(f"Error: {file_path} not found for initial data insertion.")
                return

            with open(file_path, 'r', encoding='utf-8') as f:
                initial_data = json.load(f)

            for entry_data in initial_data:
                if "_id" not in entry_data or entry_data["_id"] is None:
                    entry_data['_id'] = str(uuid.uuid4())
                
                entry_data['created_at'] = datetime.now()
                entry_data['updated_at'] = datetime.now()

                for key in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
                    if key in entry_data and isinstance(entry_data[key], str):
                        entry_data[key] = parse_peaks_string(entry_data[key])
                    elif key not in entry_data:
                        entry_data[key] = []

            if initial_data:
                entries_collection.insert_many(initial_data)
                logger.info(f"Successfully inserted {len(initial_data)} initial entries.")
            else:
                logger.warning("nmr_database.json was empty or contained no valid entries.")

        except FileNotFoundError:
            logger.error(f"nmr_database.json not found at {file_path}. Cannot insert initial data.")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding nmr_database.json: {e}")
        except Exception as e:
            logger.exception("An error occurred during initial data insertion:")
    else:
        logger.info("Database is not empty. Skipping initial data insertion.")

def add_entry(data):
    """Adds a new NMR structure entry to the database."""
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot add entry.")
        return None
    try:
        data['_id'] = str(uuid.uuid4())
        data['created_at'] = datetime.now()
        data['updated_at'] = datetime.now()

        for key in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
            if key in data and isinstance(data[key], str):
                data[key] = parse_peaks_string(data[key])
            elif key not in data:
                data[key] = []

        result = entries_collection.insert_one(data)
        if result.acknowledged:
            logger.info(f"Entry {data.get('name')} inserted successfully with ID: {data['_id']}")
            return data['_id']
        else:
            logger.error(f"Failed to insert entry: {data.get('name')}")
            return None
    except Exception as e:
        logger.exception(f"Error adding entry: {data.get('name')}")
        return None

def get_all_entries():
    """Retrieves all NMR structure entries from the database, sorted by name."""
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot fetch all entries.")
        return []
    try:
        entries = list(entries_collection.find().sort("name", 1))
        for entry in entries:
            entry['_id'] = str(entry['_id'])
        logger.info(f"Retrieved {len(entries)} entries from the database.")
        return entries
    except Exception as e:
        logger.exception("Error fetching all entries:")
        return []

def update_entry(entry_id, data):
    """Updates an existing NMR structure entry in the database."""
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot update entry.")
        return False
    try:
        update_data = {k: v for k, v in data.items() if k != '_id'}
        update_data['updated_at'] = datetime.now()

        for key in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
            if key in update_data and isinstance(update_data[key], str):
                update_data[key] = parse_peaks_string(update_data[key])
            elif key not in update_data:
                pass

        result = entries_collection.update_one({'_id': entry_id}, {'$set': update_data})
        if result.matched_count > 0:
            logger.info(f"Entry {entry_id} updated successfully. Matched: {result.matched_count}, Modified: {result.modified_count}")
            return True
        else:
            logger.warning(f"No entry found or no changes made for ID: {entry_id}. Matched: {result.matched_count}")
            return False
    except Exception as e:
        logger.exception(f"Error updating entry {entry_id}:")
        return False

def delete_entry(entry_id):
    """Deletes an NMR structure entry from the database."""
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot delete entry.")
        return False
    try:
        result = entries_collection.delete_one({'_id': entry_id})
        if result.deleted_count > 0:
            logger.info(f"Entry {entry_id} deleted successfully. Count: {result.deleted_count}")
            return True
        else:
            logger.warning(f"No entry found for deletion with ID: {entry_id}")
            return False
    except Exception as e:
        logger.exception(f"Error deleting entry {entry_id}:")
        return False

def find_entries_by_name(name):
    """Finds NMR structure entries by name (case-insensitive regex search)."""
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot find entries by name.")
        return []
    try:
        entries = list(entries_collection.find({'name': {'$regex': name, '$options': 'i'}}).sort("name", 1))
        for entry in entries:
            entry['_id'] = str(entry['_id'])
        logger.info(f"Found {len(entries)} entries matching name '{name}'.")
        return entries
    except Exception as e:
        logger.exception(f"Error finding entries by name '{name}':")
        return []

def find_entries_by_peak(peak_type, h_shift, c_shift=None, h2_shift=None):
    """Finds NMR structure entries by peak shifts and type within a tolerance."""
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot find entries by peak.")
        return []
    try:
        query = {}
        if peak_type == 'hsqc':
            query_list = []
            if h_shift is not None:
                query_list.append({f"hsqc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
            if c_shift is not None:
                query_list.append({f"hsqc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': c_shift - TOLERANCE_C_MATCH, '$lte': c_shift + TOLERANCE_C_MATCH}}}})
            if query_list:
                query = {'$and': query_list} if len(query_list) > 1 else query_list[0]
            else:
                logger.warning("HSQC search called with no valid shifts.")
                return []
        elif peak_type == 'cosy':
            query_list = []
            if h_shift is not None:
                query_list.append({f"cosy_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
            if h2_shift is not None:
                query_list.append({f"cosy_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h2_shift - TOLERANCE_H_MATCH, '$lte': h2_shift + TOLERANCE_H_MATCH}}}})
            if query_list:
                query = {'$and': query_list} if len(query_list) > 1 else query_list[0]
            else:
                logger.warning("COSY search called with no valid shifts.")
                return []
        elif peak_type == 'hmbc':
            query_list = []
            if h_shift is not None:
                query_list.append({f"hmbc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
            if c_shift is not None:
                query_list.append({f"hmbc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': c_shift - TOLERANCE_C_MATCH, '$lte': c_shift + TOLERANCE_C_MATCH}}}})
            if query_list:
                query = {'$and': query_list} if len(query_list) > 1 else query_list[0]
            else:
                logger.warning("HMBC search called with no valid shifts.")
                return []
        else: # 'all'
            or_queries = []
            if h_shift is not None:
                or_queries.append({f"hsqc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
                or_queries.append({f"hmbc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
                or_queries.append({f"cosy_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
                or_queries.append({f"cosy_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
            if c_shift is not None:
                or_queries.append({f"hsqc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': c_shift - TOLERANCE_C_MATCH, '$lte': c_shift + TOLERANCE_C_MATCH}}}})
                or_queries.append({f"hmbc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': c_shift - TOLERANCE_C_MATCH, '$lte': c_shift + TOLERANCE_C_MATCH}}}})
            
            if or_queries:
                query = {'$or': or_queries}
            else:
                logger.warning("All peak type search called with no valid shifts.")
                return []
            
        if not query:
            return []

        entries = list(entries_collection.find(query).sort("name", 1))
        unique_entries = {entry['_id']: entry for entry in entries}
        entries = list(unique_entries.values())
        
        for entry in entries:
            entry['_id'] = str(entry['_id'])
        logger.info(f"Found {len(entries)} entries matching peak search.")
        return entries
    except Exception as e:
        logger.exception(f"Error finding entries by peak (type: {peak_type}, H: {h_shift}, C: {c_shift}, H2: {h2_shift}):")
        return []
