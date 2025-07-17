import os
import uuid # For generating unique IDs
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson.objectid import ObjectId # Import ObjectId for _id handling
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime
import json
import detector
from flask_cors import CORS
import logging
import re # Import re module for regex operations
# Import the default tolerances to use as fallbacks
from detector import TOLERANCE_H_MATCH, TOLERANCE_C_MATCH

app = Flask(__name__)

# MongoDB connection setup
# MONGO_URI will be set in Render's environment variables
MONGO_URI = os.environ.get('MONGO_URI')
DB_NAME = "nmr_database_app" # This will be the name of your database inside MongoDB Atlas

client = None # Initialize client to None
db = None # Initialize db to None
entries_collection = None # Initialize entries_collection to None

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Attempt to connect to MongoDB
try:
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        # The ping command is cheap and does not require auth.
        client.admin.command('ping')
        logger.info("Successfully connected to MongoDB Atlas!")
    else:
        logger.warning("MONGO_URI environment variable not set. Attempting local MongoDB fallback.")
        client = MongoClient('mongodb://localhost:27017/')
        client.admin.command('ping')
        logger.info("Connected to local MongoDB instance (fallback).")

    # If client is successfully established, then get db and collection
    if client:
        db = client[DB_NAME]
        entries_collection = db.entries
        logger.info(f"Database '{DB_NAME}' and collection 'entries' initialized.")
        try:
            logger.info(f"Collection count: {entries_collection.count_documents({})}")
        except Exception as e:
            logger.error(f"Could not get collection count after initialization: {e}")
    else:
        logger.error("MongoDB client could not be established, 'db' and 'entries_collection' remain None.")

except ConnectionFailure as e:
    logger.error(f"MongoDB connection failed: {e}")
    entries_collection = None # Explicitly ensure it's None on failure
except OperationFailure as e:
    logger.error(f"MongoDB operation failed (authentication/authorization): {e}")
    entries_collection = None # Explicitly ensure it's None on failure
except Exception as e:
    logger.error(f"An unexpected error occurred during MongoDB setup: {e}")
    entries_collection = None # Explicitly ensure it's None on failure

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
    if not peaks_str:
        return []
    peaks = []
    # Split by lines and clean each line
    for line in peaks_str.strip().split('\n'):
        # Remove any characters that are not digits, periods, or spaces
        clean_line = re.sub(r'[^\d.\s-]', '', line).strip()
        if not clean_line:
            continue
        try:
            parts = clean_line.split()
            if len(parts) == 1:
                # Single value peak (e.g., for 1D NMR) - though current schema expects pairs
                peaks.append(float(parts[0]))
            elif len(parts) == 2:
                # Pair of values (e.g., H, C for HSQC/HMBC or H1, H2 for COSY)
                val1 = float(parts[0])
                val2 = float(parts[1])
                peaks.append((val1, val2))
            else:
                logger.warning(f"Skipping malformed peak line: {line.strip()}")
        except ValueError as e:
            logger.warning(f"Could not parse peak line '{line.strip()}': {e}")
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

def get_entry_by_id(entry_id):
    if entries_collection is None:
        logger.error("Database collection is not initialized, cannot get entry by ID.")
        return None
    try:
        # Use ObjectId for querying by _id
        entry = entries_collection.find_one({'_id': entry_id})
        if entry:
            entry['_id'] = str(entry['_id']) # Convert ObjectId to string
            logger.info(f"Retrieved entry with ID: {entry_id}")
        else:
            logger.warning(f"No entry found with ID: {entry_id}")
        return entry
    except Exception as e:
        logger.exception(f"Error fetching entry by ID {entry_id}:")
        return None

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
            logger.warning(f"No entry found for deletion with ID: {entry_id}")
            return False
    except Exception as e:
        logger.exception(f"Error deleting entry {entry_id}:")
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
            entries = get_all_entries()
        
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
        entry = get_entry_by_id(id)
        if entry:
            cleaned_entry = _recursive_clean_for_json(entry)
            return jsonify(cleaned_entry)
        else:
            logger.warning(f"Get Entry by ID: Entry with ID {id} not found.")
            return jsonify({'error': 'Entry not found'}), 404
    except Exception as e:
        logger.exception(f"Exception in get_entry_by_id_route for ID {id}:")
        return jsonify({'error': str(e)}), 500


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
            logger.info(f"Delete Entry {id}: Successfully deleted entry.")
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

        sample_peaks_str = data.get('sample_peaks')
        hsqc_data_str = data.get('hsqc_data')
        cosy_data_str = data.get('cosy_data')
        hmbc_data_str = data.get('hmbc_data')
        
        # Optional: Get custom tolerances from request, default to global if not provided
        custom_tolerance_h = data.get('tolerance_h')
        custom_tolerance_c = data.get('tolerance_c')

        if not sample_peaks_str:
            logger.error("Analyze NMR: Missing 'sample_peaks' data for analysis.")
            return jsonify({'success': False, 'error': 'Sample peaks data is required.'}), 400

        # Parse sample peaks
        sample_peaks = {
            'hsqc': detector.parse_peak_data(hsqc_data_str) if hsqc_data_str else [],
            'cosy': detector.parse_peak_data(cosy_data_str) if cosy_data_str else [],
            'hmbc': detector.parse_peak_data(hmbc_data_str) if hmbc_data_str else []
        }
        
        # Override default tolerances if custom ones are provided
        current_tolerance_h = custom_tolerance_h if custom_tolerance_h is not None else TOLERANCE_H_MATCH
        current_tolerance_c = custom_tolerance_c if custom_tolerance_c is not None else TOLERANCE_C_MATCH

        all_database_entries = get_all_entries()
        if not all_database_entries:
            logger.warning("Analyze NMR: No database entries found for comparison.")
            return jsonify({'success': False, 'error': 'No NMR structures in database for analysis.'}), 404

        results, plots = detector.analyze_mixture(
            sample_peaks,
            all_database_entries,
            tolerance_h_match=current_tolerance_h,
            tolerance_c_match=current_tolerance_c
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

if __name__ == '__main__':
    logger.info(f"Starting NMR Structure Database server...")
    
    # Only call insert_initial_data_from_json if entries_collection is available
    if entries_collection is not None:
        insert_initial_data_from_json()
    else:
        logger.error("Cannot insert initial data: entries_collection is not initialized during startup. Check MongoDB connection.")
    
    # Render automatically sets the PORT environment variable
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)