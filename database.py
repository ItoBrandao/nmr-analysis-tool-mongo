import os
import uuid
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson.objectid import ObjectId # Keep this import for potential future use or other parts of the code if they use it
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime
import json
import detector
from flask_cors import CORS
import logging
import re
from detector import TOLERANCE_H_MATCH, TOLERANCE_C_MATCH

app = Flask(__name__)
CORS(app) # Enable CORS for your Flask app if you haven't already

MONGO_URI = os.environ.get('MONGO_URI')
DB_NAME = "nmr_database_app"

client = None
db = None
entries_collection = None

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- START: DEFINITION OF insert_initial_data_from_json() FUNCTION ---
# Place the entire function definition here, before it's called
def insert_initial_data_from_json():
    global entries_collection # Ensure we're using the global variable

    if entries_collection is None:
        logger.error("Database connection not established. Cannot insert initial data.")
        return

    try:
        # Load data from the JSON file
        # The file will be in the root directory on Render
        json_file_path = 'nmr_database.json' # Make sure this file is in your project root
        if not os.path.exists(json_file_path):
            logger.error(f"Error: {json_file_path} not found.")
            return

        with open(json_file_path, 'r', encoding='utf-8') as f:
            initial_data = json.load(f)

        # Add unique IDs and timestamps
        for entry in initial_data:
            entry['_id'] = str(uuid.uuid4()) # Use UUID for _id
            entry['created_at'] = datetime.utcnow()
            entry['updated_at'] = datetime.utcnow()

            # Ensure all peak list strings are processed to lists of lists for consistency
            for peak_type in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
                if isinstance(entry.get(peak_type), str):
                    entry[peak_type] = _parse_peak_string_to_list(entry[peak_type])
                elif not isinstance(entry.get(peak_type), list):
                    entry[peak_type] = [] # Ensure it's a list even if empty/missing

        # Insert data into MongoDB
        result = entries_collection.insert_many(initial_data)
        logger.info(f"Inserted {len(result.inserted_ids)} initial entries into MongoDB.")

    except FileNotFoundError:
        logger.error(f"Error: {json_file_path} not found for initial data insertion.")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {json_file_path}: {e}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during initial data insertion: {e}")

# Helper function (keep this definition after insert_initial_data_from_json or within it if nested)
def _parse_peak_string_to_list(peak_string):
    peaks = []
    for line in peak_string.strip().split('\n'):
        parts = line.strip().split()
        if len(parts) == 2:
            try:
                # Handle ranges like "23.4-26.0" by taking the average or first value
                p1_str = parts[0]
                p2_str = parts[1]

                p1 = float(p1_str) # Assume first part is always a float

                if '-' in p2_str:
                    # If second part is a range, take the midpoint
                    range_parts = p2_str.split('-')
                    if len(range_parts) == 2:
                        p2 = (float(range_parts[0]) + float(range_parts[1])) / 2
                    else:
                        p2 = float(p2_str) # Fallback if malformed range
                else:
                    p2 = float(p2_str)

                peaks.append([p1, p2])
            except ValueError:
                logger.warning(f"Skipping malformed peak line: {line}")
        elif len(parts) > 2: # For COSY peaks "H1 H2"
            try:
                p1 = float(parts[0])
                p2 = float(parts[1])
                peaks.append([p1, p2])
            except ValueError:
                logger.warning(f"Skipping malformed COSY peak line: {line}")
    return peaks

# --- END: DEFINITION OF insert_initial_data_from_json() FUNCTION ---


# Attempt to connect to MongoDB
try:
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        client.admin.command('ping')
        logger.info("Successfully connected to MongoDB Atlas!")
        db = client[DB_NAME]
        entries_collection = db["entries"]
        
        # Removed the auto-call for insert_initial_data_from_json() from here.
        # It will now be called lazily on the first /api/entries GET request.

    else:
        logger.warning("MONGO_URI environment variable not set. Attempting local MongoDB fallback.")
        try:
            client = MongoClient('mongodb://localhost:27017/')
            db = client[DB_NAME]
            entries_collection = db["entries"]
            logger.info("Successfully connected to local MongoDB (fallback).")
            # Removed the auto-call for insert_initial_data_from_json() from here.
            # It will now be called lazily on the first /api/entries GET request.
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

# Add these debug lines right after the connection attempt
logger.info(f"MongoDB connection status: {client is not None}")
logger.info(f"Database accessible: {db is not None}")
logger.info(f"Collection initialized: {entries_collection is not None}")


CORS(app) # Enable CORS for all routes

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

# Function to parse peak data from string to list of floats/tuples
def parse_peaks_string(peaks_str):
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

def add_entry(data):
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot add entry.")
        return None
    try:
        # Generate a new unique ID
        data['_id'] = str(uuid.uuid4())
        data['created_at'] = datetime.now()
        data['updated_at'] = datetime.now()

        # Parse peak strings into appropriate formats
        for key in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
            if key in data and isinstance(data[key], str):
                data[key] = parse_peaks_string(data[key])
            elif key not in data:
                data[key] = [] # Ensure peak lists exist even if empty from input

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
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot fetch all entries.")
        return []
    try:
        entries = list(entries_collection.find().sort("name", 1)) # Sort by name
        # Convert ObjectId to string for JSON serialization
        for entry in entries:
            entry['_id'] = str(entry['_id']) # Ensure _id is a string
        logger.info(f"Retrieved {len(entries)} entries from the database.")
        return entries
    except Exception as e:
        logger.exception("Error fetching all entries:")
        return []

# Removed the old get_entry_by_id helper function as it's no longer used by the new route handler.
# If other parts of your application were calling this, they might need adjustment.

def update_entry(entry_id, data):
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot update entry.")
        return False
    try:
        # Prepare data for update, excluding _id
        update_data = {k: v for k, v in data.items() if k != '_id'}
        update_data['updated_at'] = datetime.now() # Update timestamp

        # Parse peak strings into appropriate formats for update
        for key in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
            if key in update_data and isinstance(update_data[key], str):
                update_data[key] = parse_peaks_string(update_data[key])
            elif key not in update_data:
                pass # Do nothing if key is not present in update_data

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
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot delete entry.")
        return False
    try:
        result = entries_collection.delete_one({'_id': entry_id})
        if result.deleted_count > 0:
            logger.info(f"Entry {entry_id} deleted successfully. Count: {result.deleted_count}")
            return True
        else:
            logger.warning(f"No entry found for deletion with ID: {id}")
            return False
    except Exception as e:
        logger.exception(f"Error deleting entry {id}:")
        return False

def find_entries_by_name(name):
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot find entries by name.")
        return []
    try:
        # Case-insensitive search using regex
        entries = list(entries_collection.find({'name': {'$regex': name, '$options': 'i'}}).sort("name", 1))
        for entry in entries:
            entry['_id'] = str(entry['_id']) # Convert ObjectId to string
        logger.info(f"Found {len(entries)} entries matching name '{name}'.")
        return entries
    except Exception as e:
        logger.exception(f"Error finding entries by name '{name}':")
        return []

def find_entries_by_peak(peak_type, h_shift, c_shift=None, h2_shift=None):
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
                # Use $and if both H and C shifts are provided for HSQC for a stricter match
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
            # Search across all peak types if 'all' is selected
            # This logic needs to be careful to avoid conflicting queries if multiple peak types are relevant
            # For simplicity, we will query each peak type independently and combine results, or build an $or query
            or_queries = []
            if h_shift is not None:
                # HSQC H, HMBC H, COSY H1, COSY H2
                or_queries.append({f"hsqc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
                or_queries.append({f"hmbc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
                or_queries.append({f"cosy_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
                or_queries.append({f"cosy_peaks": {'$elemMatch': {'$elemMatch': {'$gte': h_shift - TOLERANCE_H_MATCH, '$lte': h_shift + TOLERANCE_H_MATCH}}}})
            if c_shift is not None: # Only relevant for HSQC and HMBC
                or_queries.append({f"hsqc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': c_shift - TOLERANCE_C_MATCH, '$lte': c_shift + TOLERANCE_C_MATCH}}}})
                or_queries.append({f"hmbc_peaks": {'$elemMatch': {'$elemMatch': {'$gte': c_shift - TOLERANCE_C_MATCH, '$lte': c_shift + TOLERANCE_C_MATCH}}}})
            
            if or_queries:
                query = {'$or': or_queries}
            else:
                logger.warning("All peak type search called with no valid shifts.")
                return []
            
        if not query:
            return [] # No valid query built

        entries = list(entries_collection.find(query).sort("name", 1))
        # Remove duplicates if 'all' search could lead to them
        unique_entries = {entry['_id']: entry for entry in entries}
        entries = list(unique_entries.values())
        
        for entry in entries:
            entry['_id'] = str(entry['_id']) # Convert ObjectId to string
        logger.info(f"Found {len(entries)} entries matching peak search.")
        return entries
    except Exception as e:
        logger.exception(f"Error finding entries by peak (type: {peak_type}, H: {h_shift}, C: {c_shift}, H2: {h2_shift}):")
        return []

def insert_initial_data_from_json():
    # Only proceed if entries_collection is successfully initialized
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot insert initial data.")
        return

    # Check if the collection is empty
    if entries_collection.count_documents({}) == 0:
        logger.info("Database is empty. Inserting initial data from nmr_database.json...")
        try:
            # Assuming nmr_database.json is in the same directory
            script_dir = os.path.dirname(__file__)
            file_path = os.path.join(script_dir, 'nmr_database.json')

            with open(file_path, 'r', encoding='utf-8') as f:
                initial_data = json.load(f)

            for entry_data in initial_data:
                # Assign a new UUID if _id is not present or is None
                if "_id" not in entry_data or entry_data["_id"] is None:
                    entry_data['_id'] = str(uuid.uuid4())
                
                # Add timestamps
                entry_data['created_at'] = datetime.now()
                entry_data['updated_at'] = datetime.now()

                # Parse peak strings (already handled by add_entry, but ensure it's here if direct insert is used)
                for key in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
                    if key in entry_data and isinstance(entry_data[key], str):
                        entry_data[key] = parse_peaks_string(entry_data[key])
                    elif key not in entry_data:
                        entry_data[key] = [] # Ensure peak lists exist

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

# Flask Routes
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/structures.html')
def structures():
    return send_from_directory('.', 'structures.html')

@app.route('/analysis.html')
def analysis():
    return send_from_directory('.', 'analysis.html')

# API Routes
@app.route('/api/entries', methods=['GET'])
def get_entries_route():
    try:
        # Check if entries_collection is initialized BEFORE proceeding with any queries
        if entries_collection is None:
            logger.error("API GET /api/entries: entries_collection is not initialized. Returning 500 with specific error.")
            return jsonify({'error': 'Database not ready. Please check server logs for connection issues.'}), 500

        # Lazy initialization: If the collection is empty, insert initial data
        if entries_collection.count_documents({}) == 0:
            logger.info("Entries collection is empty. Inserting initial data on first GET /api/entries request.")
            insert_initial_data_from_json()

        # Get query parameters
        name_query = request.args.get('name')
        peak_type = request.args.get('peakType')
        h_shift_str = request.args.get('hShift')
        c_shift_str = request.args.get('cShift')
        h2_shift_str = request.args.get('h2Shift')

        h_shift = float(h_shift_str) if h_shift_str else None
        c_shift = float(c_shift_str) if c_shift_str else None
        h2_shift = float(h2_shift_str) if h2_shift_str else None

        entries = []
        if name_query:
            entries = find_entries_by_name(name_query)
        elif peak_type:
            entries = find_entries_by_peak(peak_type, h_shift, c_shift, h2_shift)
        else:
            entries = get_all_entries() # This should return [] if entries_collection is None, but we checked above

        # Ensure _id is string for all entries before jsonify
        cleaned_entries = [_recursive_clean_for_json(entry) for entry in entries]
        
        return jsonify(cleaned_entries)
    except Exception as e:
        logger.exception("Exception in get_entries_route:")
        return jsonify({'error': str(e)}), 500


@app.route('/api/entries', methods=['POST', 'OPTIONS'])
def add_entry_route():
    try:
        if request.method == 'OPTIONS':
            return '', 200

        if not request.is_json:
            logger.error("Add Entry: Request is not JSON.")
            return jsonify({'success': False, 'error': 'Request must be JSON'}), 400

        data = request.get_json()
        logger.info(f"Add Entry: Received data for new entry: {data}")

        if not data or not isinstance(data, dict):
            logger.error("Add Entry: Invalid data format. Data is empty or not a dictionary.")
            return jsonify({'success': False, 'error': 'Invalid data format'}), 400

        if not data.get('name'):
            logger.error("Add Entry: Missing 'name' field in request data.")
            return jsonify({'success': False, 'error': 'Structure name is required'}), 400

        logger.info(f"Add Entry: Attempting to add entry: {data.get('name')}")
        
        new_id = add_entry(data)
        if new_id:
            logger.info(f"Add Entry: Successfully added entry with ID: {new_id}")
            return jsonify({
                'success': True,
                'message': 'Entry added successfully',
                'id': new_id
            }), 201
        else:
            logger.error("Add Entry: Failed to add entry to database - add_entry function returned None.")
            return jsonify({
                'success': False,
                'error': 'Failed to add entry to database'
            }), 500

    except Exception as e:
        logger.exception("Exception in add_entry_route:") # This logs the full traceback
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/entries/<id>', methods=['GET'])
def get_entry_by_id_route(id):
    try:
        # Directly use the string ID for lookup since it's stored as a UUID string
        entry = entries_collection.find_one({'_id': id})
    except Exception as e:
        logger.exception("Error in get_entry_by_id_route")
        return jsonify({'error': str(e)}), 500

    if entry:
        # Ensure _id is returned as a string (it already is, but good for consistency)
        entry['_id'] = str(entry['_id']) 
        return jsonify(entry)
    else:
        return jsonify({'error': 'Entry not found'}), 404


@app.route('/api/entries/<id>', methods=['PUT', 'OPTIONS'])
def update_entry_route(id):
    try:
        if request.method == 'OPTIONS':
            return '', 200

        if not request.is_json:
            logger.error(f"Update Entry {id}: Request is not JSON.")
            return jsonify({'success': False, 'error': 'Request must be JSON'}), 400

        data = request.get_json()
        logger.info(f"Update Entry {id}: Received data for update: {data}")

        if not data or not isinstance(data, dict):
            logger.error(f"Update Entry {id}: Invalid data format. Data is empty or not a dictionary.")
            return jsonify({'success': False, 'error': 'Invalid data format'}), 400

        if not data.get('name'): # Ensure name is present for updates too, as it's a critical field
            logger.warning(f"Update Entry {id}: 'name' field is missing in update data. Proceeding, but name might not be updated or validated.")
            # Depending on requirements, you might want to return 400 here if 'name' is mandatory for updates.

        logger.info(f"Update Entry {id}: Attempting to update entry: {data.get('name', 'N/A')}")

        success = update_entry(id, data)
        if success:
            logger.info(f"Update Entry {id}: Successfully updated entry.")
            return jsonify({
                'success': True,
                'message': 'Entry updated successfully'
            }), 200
        else:
            logger.error(f"Update Entry {id}: Failed to update entry. Entry not found or no changes were made.")
            return jsonify({
                'success': False,
                'error': 'Failed to update entry. Entry not found or no changes were made.'
            }), 404 # 404 if not found, 500 for other failures

    except Exception as e:
        logger.exception(f"Exception in update_entry_route for ID {id}:") # This logs the full traceback
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/entries/<id>', methods=['DELETE', 'OPTIONS'])
def delete_entry_route(id):
    try:
        if request.method == 'OPTIONS':
            return '', 200
        
        logger.info(f"Delete Entry {id}: Attempting to delete entry.")

        success = delete_entry(id)
        if success:
            logger.info(f"Entry {id}: Successfully deleted entry.")
            return jsonify({
                'success': True,
                'message': 'Entry deleted successfully'
            }), 200
        else:
            logger.warning(f"Delete Entry {id}: No entry found for deletion with ID: {id}.")
            return jsonify({
                'success': False,
                'error': 'Entry not found or already deleted.'
            }), 404
    except Exception as e:
        logger.exception(f"Exception in delete_entry_route for ID {id}:")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze_nmr_route():
    try:
        if request.method == 'OPTIONS':
            return '', 200

        if not request.is_json:
            logger.error("Analyze NMR: Request is not JSON")
            return jsonify({'success': False, 'error': 'Request must be JSON'}), 400

        data = request.get_json()
        logger.info(f"Analyze NMR: Received data for analysis. Keys: {list(data.keys())}")

        
        hsqc_data_str = data.get('hsqc_data')
        cosy_data_str = data.get('cosy_data')
        hmbc_data_str = data.get('hmbc_data')
        
        # Optional: Get custom tolerances from request, default to global if not provided
        custom_tolerance_h = data.get('tolerance_h')
        custom_tolerance_c = data.get('tolerance_c')


        # Override default tolerances if custom ones are provided
        current_tolerance_h = custom_tolerance_h if custom_tolerance_h is not None else TOLERANCE_H_MATCH
        current_tolerance_c = custom_tolerance_c if custom_tolerance_c is not None else TOLERANCE_C_MATCH

        all_database_entries = get_all_entries()
        if not all_database_entries:
            logger.warning("Analyze NMR: No database entries found for comparison.")
            return jsonify({'success': False, 'error': 'No NMR structures in database for analysis.'}), 404

        results, plots = detector.analyze_mixture(
                hsqc_data_str,
                cosy_data_str,
                hmbc_data_str,
                all_database_entries,
                tolerance_h=current_tolerance_h,
                tolerance_c=current_tolerance_c
        )
        
        # Apply _recursive_clean_for_json to the results dictionary
        cleaned_results = _recursive_clean_for_json({
            'detected_entries': results['detected_entries'],
            'unmatched_sample_peaks': results['unmatched_sample_peaks'],
        })
        
        return jsonify({
            'success': True,
            'detected_entries': cleaned_results['detected_entries'],
            'unmatched_sample_peaks': cleaned_results['unmatched_sample_peaks'],
            'hsqc_image_base64': plots[0] if plots[0] else None,
            'cosy_image_base64': plots[1] if plots[1] else None,
            'hmbc_image_base64': plots[2] if plots[2] else None
        })
    except Exception as e:
        logger.exception(f"Exception in analyze_nmr_route:")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ---------------------------------------------------------------
# NEW QUICK HSQC MATCHER (Blueprint to avoid separate Procfile)
# ---------------------------------------------------------------
from flask import Blueprint, request, render_template_string
from compare_nmr_peaks import compare_peaks as _compare_peaks   # renamed import

quick_bp = Blueprint('quick_hsqc', __name__, url_prefix='/quick-hsqc')

@quick_bp.route("/")
def quick_index():
    return QUICK_HTML

@quick_bp.route("/api/match", methods=["POST"])
def quick_api():
    data = request.get_json()
    peaks  = data.get("peaks", "")
    d1h    = float(data.get("d1h", 0.06))
    d13c   = float(data.get("d13c", 0.8))
    if not peaks.strip():
        return jsonify({"error": "No peaks provided"}), 400
    return jsonify(_compare_peaks(peaks, delta_1H=d1h, delta_13C=d13c))

# HTML embedded to avoid templates
QUICK_HTML = """
<!doctype html>
<html>
<head>
  <title>Quick HSQC Matcher</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:Arial;margin:40px;background:#f9f9f9}
    textarea{width:100%;height:160px;font-family:monospace}
    label{display:block;margin-top:10px}
    button{margin-top:15px;padding:8px 18px}
    .results{margin-top:30px}
    .results ul{margin:0;padding-left:20px}
  </style>
</head>
<body>
  <h2>Quick HSQC matcher</h2>
  <p>Paste your HSQC peaks (1H 13C Intensity, one per line):</p>
  <textarea id="peaks" placeholder="3.31 49.1 1.0\n7.20 128 0.5"></textarea>

  <label>1H tolerance (ppm) <input type="number" id="d1h" value="0.06" step="0.01"></label>
  <label>13C tolerance (ppm) <input type="number" id="d13c" value="0.8" step="0.1"></label>

  <button onclick="run()">Find matches</button>

  <div class="results">
    <div id="full"></div>
    <div id="part"></div>
  </div>

<script>
async function run() {
  const peaks = document.getElementById('peaks').value;
  const d1h   = document.getElementById('d1h').value;
  const d13c  = document.getElementById('d13c').value;
  const res   = await fetch('/quick-hsqc/api/match', {
                     method:'POST',
                     headers:{'Content-Type':'application/json'},
                     body: JSON.stringify({peaks, d1h, d13c})});
  const json  = await res.json();
  document.getElementById('full').innerHTML =
      '<h3>Fully matched</h3><ul>' +
      (json.fully.length ? json.fully.map(x=>'<li>'+x) : ['<li>None']) +
      '</ul>';
  document.getElementById('part').innerHTML =
      '<h3>Partial (≥50%)</h3><ul>' +
      (json.partial.length ? json.partial.map(x=>'<li>'+x.id+'  '+x.ratio+'  '+x.percent) : ['<li>None']) +
      '</ul>';
}
</script>
</body>
</html>
"""

# Register the blueprint
app.register_blueprint(quick_bp)
