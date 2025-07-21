from flask import Flask, render_template, request, jsonify
import json
import os
import logging

# Import comparison logic and database operations
from compare_nmr_peaks import compare_peaks
import detector
import db_operations  # Renamed database.py to db_operations.py

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize database connection on app startup
@app.before_request
def initialize_db():
    # This will ensure the database connection is attempted and initial data inserted if needed
    # It's called before each request, but the db_operations functions handle
    # lazy initialization and checking if data already exists.
    logger.debug("Attempting to initialize database before request.")
    db_operations.initialize_db_connection()

# Define the route for the main page
@app.route('/')
def index():
    # This will serve the index.html content (Add/Edit Structure page)
    return render_template('index.html')

# Define the route for the structures page
@app.route('/structures.html')
def structures():
    # This will serve the structures.html content (View/Search Structures page)
    return render_template('structures.html')

# Define the route for the analysis page
@app.route('/analysis.html')
def analysis():
    # This will serve the analysis.html content (NMR Analysis page)
    return render_template('analysis.html')

# Define the route for the compare page
@app.route('/compare.html')
def compare():
    # This will serve the compare.html content (Compare NMR Peaks page)
    return render_template('compare.html')

# API Routes for NMR Structure Database (from original database.py)
@app.route('/api/entries', methods=['GET'])
def get_entries_route():
    try:
        if db_operations.entries_collection is None:
            logger.error("API GET /api/entries: entries_collection is not initialized. Returning 500.")
            return jsonify({'error': 'Database not ready. Please check server logs for connection issues.'}), 500

        # Lazy initialization: If the collection is empty, insert initial data
        if db_operations.entries_collection.count_documents({}) == 0:
            logger.info("Entries collection is empty. Inserting initial data on first GET /api/entries request.")
            db_operations.insert_initial_data_from_json()

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
            entries = db_operations.find_entries_by_name(name_query)
        elif peak_type:
            entries = db_operations.find_entries_by_peak(peak_type, h_shift, c_shift, h2_shift)
        else:
            entries = db_operations.get_all_entries()

        cleaned_entries = [db_operations._recursive_clean_for_json(entry) for entry in entries]
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
        
        new_id = db_operations.add_entry(data)
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
        logger.exception("Exception in add_entry_route:")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/entries/<id>', methods=['GET'])
def get_entry_by_id_route(id):
    try:
        entry = db_operations.entries_collection.find_one({'_id': id})
    except Exception as e:
        logger.exception("Error in get_entry_by_id_route")
        return jsonify({'error': str(e)}), 500

    if entry:
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

        success = db_operations.update_entry(id, data)
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
            }), 404

    except Exception as e:
        logger.exception(f"Exception in update_entry_route for ID {id}:")
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

        success = db_operations.delete_entry(id)
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
        
        custom_tolerance_h = data.get('tolerance_h')
        custom_tolerance_c = data.get('tolerance_c')

        current_tolerance_h = custom_tolerance_h if custom_tolerance_h is not None else detector.TOLERANCE_H_MATCH
        current_tolerance_c = custom_tolerance_c if custom_tolerance_c is not None else detector.TOLERANCE_C_MATCH

        all_database_entries = db_operations.get_all_entries()
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
        
        cleaned_results = db_operations._recursive_clean_for_json({
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

# API endpoint for comparing HSQC peaks to database_input.csv
@app.route('/api/quick-match', methods=['POST', 'OPTIONS'])
def quick_match_api():
    try:
        if request.method == 'OPTIONS':
            return '', 200

        data = request.get_json()
        hsqc_peaks_str = data.get('hsqcPeaks', '')
        delta_1H = float(data.get('d1h', 0.06))
        delta_13C = float(data.get('d13c', 0.8))

        if not hsqc_peaks_str.strip():
            return jsonify({"error": "No HSQC peaks provided"}), 400
        
        # Call the compare_peaks function from compare_nmr_peaks.py
        results = compare_peaks(hsqc_peaks_str, delta_1H=delta_1H, delta_13C=delta_13C)
        
        return jsonify(results)
    except Exception as e:
        logger.exception("Error in quick_match_api:")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)