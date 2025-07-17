import os
import uuid
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson.objectid import ObjectId
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
# This entire function definition MUST be placed here, before it's called
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
        
        # --- NEW LOCATION FOR CALLING insert_initial_data_from_json() ---
        logger.info(f"Checking if '{DB_NAME}' database and 'entries' collection need initial data...")
        if entries_collection.count_documents({}) == 0:
            insert_initial_data_from_json() # Now the function is defined above!
        else:
            logger.info("Entries collection is not empty, skipping initial data insertion.")
        # --- END NEW LOCATION FOR CALL ---

    else:
        logger.warning("MONGO_URI environment variable not set. Attempting local MongoDB fallback.")
        try:
            client = MongoClient('mongodb://localhost:27017/')
            db = client[DB_NAME]
            entries_collection = db["entries"]
            logger.info("Successfully connected to local MongoDB (fallback).")
            if entries_collection.count_documents({}) == 0:
                insert_initial_data_from_json() # Call for local fallback too
            else:
                logger.info("Entries collection is not empty locally, skipping initial data insertion.")
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

# ----------------------------------------------------------------------
# Flask Routes - Keep these as they are, below the database setup
# ----------------------------------------------------------------------

# Serve static files from 'static' directory (for CSS, JS, images)
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/structures')
def structures():
    return send_from_directory('.', 'structures.html')

@app.route('/analysis')
def analysis():
    return send_from_directory('.', 'analysis.html')

@app.route('/api/entries', methods=['GET'])
def get_entries():
    if entries_collection is None:
        return jsonify({"success": False, "error": "Database connection not available"}), 500
    
    try:
        query = {}
        compound_name = request.args.get('compound_name')
        if compound_name:
            # Use regex for case-insensitive partial match
            query['name'] = {'$regex': compound_name, '$options': 'i'}
        
        entry_id = request.args.get('id')
        if entry_id:
            query['_id'] = entry_id

        # Peak search parameters
        peak_type = request.args.get('peak_type')
        peak1_str = request.args.get('peak1')
        peak2_str = request.args.get('peak2')

        if peak_type and (peak1_str or peak2_str):
            try:
                peak1 = float(peak1_str) if peak1_str else None
                peak2 = float(peak2_str) if peak2_str else None

                peak_query_list = []

                if peak_type == 'hsqc' and peak1 is not None and peak2 is not None:
                    peak_query_list.append({
                        'hsqc_peaks': {'$elemMatch': {
                            '$and': [
                                {'$gte': peak1 - TOLERANCE_H_MATCH, '$lte': peak1 + TOLERANCE_H_MATCH},
                                {'$gte': peak2 - TOLERANCE_C_MATCH, '$lte': peak2 + TOLERANCE_C_MATCH}
                            ]
                        }}
                    })
                elif peak_type == 'cosy' and peak1 is not None and peak2 is not None:
                    peak_query_list.append({
                        'cosy_peaks': {'$elemMatch': {
                            '$and': [
                                {'$gte': peak1 - TOLERANCE_H_MATCH, '$lte': peak1 + TOLERANCE_H_MATCH},
                                {'$gte': peak2 - TOLERANCE_H_MATCH, '$lte': peak2 + TOLERANCE_H_MATCH}
                            ]
                        }}
                    })
                elif peak_type == 'hmbc' and peak1 is not None and peak2 is not None:
                    peak_query_list.append({
                        'hmbc_peaks': {'$elemMatch': {
                            '$and': [
                                {'$gte': peak1 - TOLERANCE_H_MATCH, '$lte': peak1 + TOLERANCE_H_MATCH},
                                {'$gte': peak2 - TOLERANCE_C_MATCH, '$lte': peak2 + TOLERANCE_C_MATCH}
                            ]
                        }}
                    })
                elif peak_type == 'all' and peak1 is not None: # Search for any peak type with peak1 only
                    all_peak_types_query = []
                    all_peak_types_query.append({'hsqc_peaks': {'$elemMatch': {'$or': [{'0': {'$gte': peak1 - TOLERANCE_H_MATCH, '$lte': peak1 + TOLERANCE_H_MATCH}}, {'1': {'$gte': peak1 - TOLERANCE_C_MATCH, '$lte': peak1 + TOLERANCE_C_MATCH}}]}}})
                    all_peak_types_query.append({'cosy_peaks': {'$elemMatch': {'$or': [{'0': {'$gte': peak1 - TOLERANCE_H_MATCH, '$lte': peak1 + TOLERANCE_H_MATCH}}, {'1': {'$gte': peak1 - TOLERANCE_H_MATCH, '$lte': peak1 + TOLERANCE_H_MATCH}}]}}})
                    all_peak_types_query.append({'hmbc_peaks': {'$elemMatch': {'$or': [{'0': {'$gte': peak1 - TOLERANCE_H_MATCH, '$lte': peak1 + TOLERANCE_H_MATCH}}, {'1': {'$gte': peak1 - TOLERANCE_C_MATCH, '$lte': peak1 + TOLERANCE_C_MATCH}}]}}})
                    peak_query_list.append({'$or': all_peak_types_query})
                
                if peak_query_list:
                    if query: # If there's an existing compound name query
                        query = {'$and': [query, {'$or': peak_query_list}]}
                    else:
                        query = {'$or': peak_query_list}


            except ValueError:
                return jsonify({"success": False, "error": "Invalid peak value. Please provide numeric values."}), 400
        
        entries = list(entries_collection.find(query))
        
        # Convert ObjectId to string for JSON serialization
        for entry in entries:
            if '_id' in entry and isinstance(entry['_id'], ObjectId):
                entry['_id'] = str(entry['_id'])
        
        return jsonify({"success": True, "entries": entries})
    except Exception as e:
        logger.exception("Exception in get_entries:")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/entry', methods=['POST'])
def add_entry():
    if entries_collection is None:
        return jsonify({"success": False, "error": "Database connection not available"}), 500

    data = request.json
    
    # Generate a new unique ID and set timestamps
    data['_id'] = str(uuid.uuid4())
    data['created_at'] = datetime.utcnow()
    data['updated_at'] = datetime.utcnow()

    # Process peak lists from string to list of lists
    for peak_type in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
        if isinstance(data.get(peak_type), str):
            data[peak_type] = _parse_peak_string_to_list(data[peak_type])
        elif not isinstance(data.get(peak_type), list):
            data[peak_type] = [] # Ensure it's a list even if empty/missing
            
    try:
        result = entries_collection.insert_one(data)
        logger.info(f"Added new entry with ID: {data['_id']}")
        return jsonify({"success": True, "id": data['_id']}), 201
    except Exception as e:
        logger.exception("Exception in add_entry:")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/entry/<string:entry_id>', methods=['PUT'])
def update_entry(entry_id):
    if entries_collection is None:
        return jsonify({"success": False, "error": "Database connection not available"}), 500

    data = request.json
    
    # Remove _id from data to prevent it from being updated
    data.pop('_id', None) 
    data['updated_at'] = datetime.utcnow() # Update timestamp

    # Process peak lists from string to list of lists for update
    for peak_type in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
        if isinstance(data.get(peak_type), str):
            data[peak_type] = _parse_peak_string_to_list(data[peak_type])
        elif not isinstance(data.get(peak_type), list):
            data[peak_type] = [] # Ensure it's a list even if empty/missing

    try:
        # Use str(ObjectId(entry_id)) to handle cases where _id might be stored as ObjectId
        result = entries_collection.update_one({'_id': entry_id}, {'$set': data})
        
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Entry not found"}), 404
        logger.info(f"Updated entry with ID: {entry_id}")
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("Exception in update_entry:")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/entry/<string:entry_id>', methods=['DELETE'])
def delete_entry(entry_id):
    if entries_collection is None:
        return jsonify({"success": False, "error": "Database connection not available"}), 500
        
    try:
        # Use str(ObjectId(entry_id)) to handle cases where _id might be stored as ObjectId
        result = entries_collection.delete_one({'_id': entry_id})
        
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "Entry not found"}), 404
        logger.info(f"Deleted entry with ID: {entry_id}")
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("Exception in delete_entry:")
        return jsonify({"success": False, "error": str(e)}), 500

def _recursive_clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: _recursive_clean_for_json(v) for k, v in obj.items() if k != '_id'}
    elif isinstance(obj, list):
        return [_recursive_clean_for_json(elem) for elem in obj]
    elif isinstance(obj, ObjectId): # Handle ObjectId if it somehow made it here
        return str(obj)
    elif isinstance(obj, datetime): # Convert datetime objects to ISO format strings
        return obj.isoformat()
    return obj

@app.route('/api/analyze_nmr', methods=['POST'])
def analyze_nmr_route():
    if entries_collection is None:
        return jsonify({"success": False, "error": "Database connection not available"}), 500

    data = request.json
    
    sample_hsqc_str = data.get('hsqc_peaks', '')
    sample_cosy_str = data.get('cosy_peaks', '')
    sample_hmbc_str = data.get('hmbc_peaks', '')

    current_tolerance_h = float(data.get('tolerance_h', TOLERANCE_H_MATCH))
    current_tolerance_c = float(data.get('tolerance_c', TOLERANCE_C_MATCH))
    
    # Prepare sample peaks by parsing them from string inputs
    sample_peaks = {
        'hsqc': _parse_peak_string_to_list(sample_hsqc_str),
        'cosy': _parse_peak_string_to_list(sample_cosy_str),
        'hmbc': _parse_peak_string_to_list(sample_hmbc_str)
    }
    
    # Retrieve all entries from the database
    database_entries = list(entries_collection.find({}))
    
    # Pre-process database entries to ensure peak lists are in correct format
    for entry in database_entries:
        # Convert ObjectId to string for consistency if it exists
        if '_id' in entry and isinstance(entry['_id'], ObjectId):
            entry['_id'] = str(entry['_id'])

        for peak_type in ['hsqc_peaks', 'cosy_peaks', 'hmbc_peaks']:
            if isinstance(entry.get(peak_type), str):
                entry[peak_type] = _parse_peak_string_to_list(entry[peak_type])
            elif not isinstance(entry.get(peak_type), list):
                entry[peak_type] = [] # Ensure it's a list even if empty/missing

    try:
        # Perform analysis
        results, plots = detector.analyze_mixture(
            sample_peaks,
            database_entries,
            current_tolerance_h,
            current_tolerance_c
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

# Remove the old `if __name__ == '__main__':` block if it's still there