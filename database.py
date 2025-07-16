import os
import uuid # For generating unique IDs
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime
import json
import detector
from flask_cors import CORS
import logging
# Import the default tolerances to use as fallbacks
from detector import TOLERANCE_H_MATCH, TOLERANCE_C_MATCH

app = Flask(__name__)

# MongoDB connection setup
# MONGO_URI will be set in Render's environment variables
MONGO_URI = os.environ.get('MONGO_URI')
DB_NAME = "nmr_database_app" # This will be the name of your database inside MongoDB Atlas

client = None # Initialize client and db to None
db = None

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

if not MONGO_URI:
    logger.error("MONGO_URI environment variable not set. Please set it for database connection.")
    # Fallback for local testing if MONGO_URI is not set, using a local MongoDB instance
    # You would need to run a local MongoDB server for this to work, otherwise db will be None.
    try:
        client = MongoClient('mongodb://localhost:27017/')
        db = client[DB_NAME]
        logger.warning("Using local MongoDB connection (MONGO_URI not set for deployment).")
    except ConnectionFailure as e:
        logger.error(f"Could not connect to local MongoDB: {e}. Data will not be persistent.")
        client = None
        db = None
else:
    try:
        client = MongoClient(MONGO_URI)
        # The ismaster command is cheap and does not require auth.
        client.admin.command('ismaster')
        db = client[DB_NAME]
        logger.info(f"Connected to MongoDB Atlas database: {DB_NAME}")
    except ConnectionFailure as e:
        logger.error(f"Could not connect to MongoDB Atlas at {MONGO_URI}: {e}. Data will not be persistent.")
        client = None
        db = None
    except OperationFailure as e:
        logger.error(f"Authentication or operation failure with MongoDB Atlas: {e}. Check MONGO_URI credentials.")
        client = None
        db = None

# Configure CORS to allow all methods for all routes starting with '/'
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Function to insert data from nmr_database.json into MongoDB (one-time use if starting fresh)
def insert_initial_data_from_json():
    if db is None:
        logger.error("Database connection not established. Cannot insert initial data.")
        return

    json_file_path = 'nmr_database.json'
    if os.path.exists(json_file_path):
        with open(json_file_path, 'r') as f:
            initial_data = json.load(f)

        entries_collection = db.entries # 'entries' will be the name of your collection
        # Check if collection is empty before inserting
        if entries_collection.count_documents({}) == 0:
            # Add 'id' field if not present, and ensure it's a string, important for updates/deletes later
            for entry in initial_data:
                if 'id' not in entry or not entry['id']:
                    entry['id'] = str(uuid.uuid4())
                if 'created_at' not in entry:
                    entry['created_at'] = datetime.utcnow().isoformat()
            entries_collection.insert_many(initial_data)
            logger.info(f"Inserted {len(initial_data)} initial entries from {json_file_path} into MongoDB.")
        else:
            logger.info("MongoDB 'entries' collection is not empty, skipping initial JSON data import.")
    else:
        logger.info(f"No initial {json_file_path} found to import.")

# New functions to interact with MongoDB
def get_all_entries():
    if db is None:
        logger.error("Database connection not established. Cannot get entries.")
        return []
    entries_collection = db.entries
    # Convert _id (ObjectId from MongoDB) to string for JSON serialization
    return [{**entry, '_id': str(entry['_id'])} for entry in entries_collection.find({})]

def find_entry_by_id(entry_id):
    if db is None:
        logger.error("Database connection not established. Cannot find entry by ID.")
        return None
    entries_collection = db.entries
    # Query using the 'id' field which we control, not MongoDB's '_id'
    entry = entries_collection.find_one({'id': str(entry_id)})
    return {**entry, '_id': str(entry['_id'])} if entry else None

def add_entry(entry):
    if db is None:
        logger.error("Database connection not established. Cannot add entry.")
        return None
    entries_collection = db.entries
    if 'id' not in entry or not entry['id']:
        entry['id'] = str(uuid.uuid4()) # Generate unique ID if not provided
    entry['created_at'] = datetime.utcnow().isoformat()
    # Add 'updated_at' if not present (e.g., when adding a new entry for the first time)
    if 'updated_at' not in entry:
        entry['updated_at'] = datetime.utcnow().isoformat()
    result = entries_collection.insert_one(entry)
    if result.inserted_id:
        logger.info(f"Added new entry with ID: {entry['id']}")
        return entry['id']
    logger.error(f"Failed to add entry {entry['id']}.")
    return None

def update_entry(entry_id, updated_data):
    if db is None:
        logger.error("Database connection not established. Cannot update entry.")
        return False
    entries_collection = db.entries
    updated_data['updated_at'] = datetime.utcnow().isoformat()
    result = entries_collection.update_one({'id': str(entry_id)}, {'$set': updated_data})
    if result.modified_count > 0:
        logger.info(f"Updated entry with ID: {entry_id}")
        return True
    logger.warning(f"No entry found or modified for ID: {entry_id}")
    return False

def delete_entry(entry_id):
    if db is None:
        logger.error("Database connection not established. Cannot delete entry.")
        return False
    entries_collection = db.entries
    result = entries_collection.delete_one({'id': str(entry_id)})
    if result.deleted_count > 0:
        logger.info(f"Deleted entry with ID: {entry_id}")
        return True
    logger.warning(f"No entry found or deleted for ID: {entry_id}")
    return False

def _clean_entry(entry):
    """Clean entry for API response by removing internal DataFrame fields."""
    if not isinstance(entry, dict):
        return {}

    cleaned = entry.copy()
    # Remove internal fields that are not needed in the front-end
    for peak_type in ['hsqc', 'cosy', 'hmbc']:
        # The .pop(key, None) safely removes the key if it exists
        cleaned.pop(f'{peak_type}_peaks_parsed', None)
    return cleaned

def _to_json_serializable(obj):
    """Recursively convert DataFrame objects within a dictionary or list to a JSON-serializable format."""
    # Check if pandas is imported and obj is a DataFrame
    if 'pd' in globals() and isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient='split')  # More robust serialization
    elif isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_to_json_serializable(elem) for elem in obj]
    else:
        return obj

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/api/entries', methods=['GET', 'OPTIONS'])
def get_entries():
    try:
        # For OPTIONS requests, just return 200 OK without parsing JSON
        if request.method == 'OPTIONS':
            return '', 200

        db_entries_from_mongo = get_all_entries() # Get all entries from MongoDB
        search = request.args.get('search', '').lower()
        name_search = request.args.get('nameSearch', '').lower()
        peak_type = request.args.get('peakType', 'all')
        
        filtered = []
        for entry in db_entries_from_mongo: # Iterate through MongoDB entries
            if not isinstance(entry, dict):
                continue
                
            # Filter by name if search term provided
            if name_search and name_search not in entry.get('name', '').lower():
                continue
                
            # Filter by peak type if specified
            if peak_type != 'all':
                peak_key = f'{peak_type}_peaks'
                if not entry.get(peak_key):
                    continue
            
            filtered.append(_clean_entry(entry))
            
        return jsonify({
            'success': True,
            'data': filtered,
            'count': len(filtered)
        })
    except Exception as e:
        logger.error(f"Error in get_entries: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/entries/<int:entry_id>', methods=['GET', 'OPTIONS'])
def get_entry(entry_id):
    try:
        # For OPTIONS requests, just return 200 OK without parsing JSON
        if request.method == 'OPTIONS':
            return '', 200

        # Use the new MongoDB helper function
        entry = find_entry_by_id(entry_id)
        if entry:
            # Clean the entry before returning for consistency with old behavior
            return jsonify({
                'success': True,
                'data': _clean_entry(entry)
            })
        return jsonify({
            'success': False,
            'error': 'Entry not found'
        }), 404
    except Exception as e:
        logger.error(f"Error in get_entry: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/entries', methods=['POST', 'OPTIONS'])
def add_entry_route(): # Renamed to avoid conflict with helper function name
    try:
        # For OPTIONS requests, just return 200 OK without parsing JSON
        if request.method == 'OPTIONS':
            return '', 200

        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Request must be JSON'
            }), 400

        data = request.get_json()
        logger.debug(f"Received data for new entry: {data}")

        # Validate required fields
        if not data or not isinstance(data, dict):
            return jsonify({
                'success': False,
                'error': 'Invalid data format'
            }), 400

        if not data.get('name'):
            return jsonify({
                'success': False,
                'error': 'Structure name is required'
            }), 400

        # The 'id' generation and 'created_at' timestamp are now handled
        # by the `add_entry` MongoDB helper function we created earlier.
        # We ensure 'updated_at' is set here before passing to the helper.
        data['updated_at'] = datetime.utcnow().isoformat()

        # Parse peaks and store both raw and parsed versions (KEEP THIS SECTION AS IS)
        # This part processes your peak data before saving it to the database
        for peak_type in ['hsqc', 'cosy', 'hmbc']:
            if peak_type in data:
                try:
                    parsed = detector.parse_peak_data(data[peak_type], peak_type)
                    data[f'{peak_type}_peaks_parsed'] = parsed
                except Exception as e:
                    logger.error(f"Error parsing {peak_type} peaks: {str(e)}")
                    return jsonify({
                        'success': False,
                        'error': f'Error parsing {peak_type.upper()} peaks: {str(e)}'
                    }), 400
            else:
                # Ensure parsed key exists even if no raw data provided, as an empty DataFrame
                data[f'{peak_type}_peaks_parsed'] = pd.DataFrame()

        # Use the new MongoDB add_entry helper function to save the data
        new_id = add_entry(data)

        if new_id:
            logger.info(f"Successfully added new entry with ID {new_id}")
            return jsonify({
                'success': True,
                'message': 'Entry added successfully',
                'id': new_id
            }), 201
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to add entry to database.'
            }), 500

    except Exception as e:
        logger.error(f"Error in add_entry_route: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/entries/<int:entry_id>', methods=['PUT', 'OPTIONS'])
def update_entry_route(entry_id): # Renamed to avoid conflict with helper function name
    try:
        # For OPTIONS requests, just return 200 OK without parsing JSON
        if request.method == 'OPTIONS':
            return '', 200

        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Request must be JSON'
            }), 400
            
        data = request.get_json()
        logger.debug(f"Updating entry {entry_id} with data: {data}")
        
        # Ensure 'updated_at' is always current
        data['updated_at'] = datetime.utcnow().isoformat()

        # Parse peaks if they were updated (KEEP THIS LOGIC AS IS)
        for peak_type in ['hsqc', 'cosy', 'hmbc']:
            if peak_type in data: # Check if raw peaks were sent in the update request
                try:
                    parsed = detector.parse_peak_data(data[peak_type], peak_type)
                    data[f'{peak_type}_peaks_parsed'] = parsed
                except Exception as e:
                    logger.error(f"Error parsing {peak_type} peaks: {str(e)}")
                    return jsonify({
                        'success': False,
                        'error': f'Error parsing {peak_type.upper()} peaks: {str(e)}'
                    }), 400
            elif f'{peak_type}_peaks_parsed' not in data:
                # If raw peaks not updated and parsed peaks not in the new data,
                # fetch existing entry to decide if _peaks_parsed should be kept or set to empty.
                # Simplified: if not in data, assume no update to peaks, keep existing or leave as is.
                # The update_entry helper will handle merging if a key isn't explicitly set.
                pass # No action needed here, let the $set in update_entry handle it.

        # Use the new MongoDB update_entry helper function
        if update_entry(entry_id, data):
            # Fetch the updated entry to return it in the response
            updated_entry = find_entry_by_id(entry_id)
            return jsonify({
                'success': True,
                'data': _clean_entry(updated_entry),
                'message': 'Entry updated successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Entry not found or no changes made'
            }), 404
    except Exception as e:
        logger.error(f"Error in update_entry_route: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/entries/<int:entry_id>', methods=['DELETE', 'OPTIONS'])
def delete_entry_route(entry_id): # Renamed to avoid conflict with helper function name
    try:
        # For OPTIONS requests, just return 200 OK without parsing JSON
        if request.method == 'OPTIONS':
            return '', 200

        # Use the new MongoDB delete_entry helper function
        if delete_entry(entry_id):
            logger.info(f"Successfully deleted entry with ID {entry_id}")
            return jsonify({
                'success': True,
                'message': 'Entry deleted successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Entry not found'
            }), 404
    except Exception as e:
        logger.error(f"Error in delete_entry_route: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/analyze-mixture', methods=['POST', 'OPTIONS'])
def analyze_nmr():
    try:
        # For OPTIONS requests, just return 200 OK without parsing JSON
        if request.method == 'OPTIONS':
            return '', 200

        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Request must be JSON'
            }), 400
            
        data = request.get_json()
        logger.debug(f"Running analysis with data: {data}")
        
        # Use the new MongoDB helper function to get all entries
        db_entries_from_mongo = get_all_entries() 
        
        # --- CHANGE START: Get tolerances from request or use defaults ---
        tolerance_h = data.get('toleranceH', TOLERANCE_H_MATCH)
        tolerance_c = data.get('toleranceC', TOLERANCE_C_MATCH)
        logger.debug(f"Using Tolerances -> H: {tolerance_h}, C: {tolerance_c}")
        # --- CHANGE END ---
        
        # Extract num_contour_levels from request, with a default of 15
        num_contour_levels = data.get('num_contour_levels', 15)

        # --- CHANGE START: Pass tolerances to the analysis function ---
        results = detector.run_analysis(
            data.get('hsqc_peaks', ''),
            data.get('cosy_peaks', ''),
            data.get('hmbc_peaks', ''),
            db_entries_from_mongo, # Use the entries from MongoDB
            tolerance_h,
            tolerance_c
        )
        # --- CHANGE END ---
        
        plots = detector.generate_nmr_plots(
            data.get('hsqc_peaks', ''),
            data.get('cosy_peaks', ''),
            data.get('hmbc_peaks', ''),
            num_contour_levels
        )

        # --- CHANGE START: Clean compound data before sending response ---
        for result_entry in results.get('detected_entries', []):
            if 'compound' in result_entry and isinstance(result_entry['compound'], dict):
                result_entry['compound'] = _clean_entry(result_entry['compound'])
        # --- CHANGE END ---

        # Apply the recursive cleaning function to the results dictionary
        cleaned_results = _to_json_serializable({
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
        logger.error(f"Error in analyze_nmr: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    logger.info(f"Starting NMR Structure Database server on http://127.0.0.1:5000/")
    
    # Call the function to insert initial data from JSON if the collection is empty
    insert_initial_data_from_json()
    
    app.run(debug=True, host='0.0.0.0')