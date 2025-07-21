from flask import Flask, request, render_template_string, jsonify
import json
import os
import logging

# Import comparison logic and database operations
from compare_nmr_peaks import compare_peaks
import detector
import db_operations # Renamed database.py to db_operations.py

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
    return render_template_string(INDEX_PAGE)

# Define the route for the structures page
@app.route('/structures.html')
def structures():
    # This will serve the structures.html content (View/Search Structures page)
    return render_template_string(STRUCTURES_PAGE)

# Define the route for the analysis page
@app.route('/analysis.html')
def analysis():
    # This will serve the analysis.html content (NMR Analysis page)
    return render_template_string(ANALYSIS_PAGE)

# Define the route for the compare page
@app.route('/compare.html')
def compare():
    # This will serve the compare.html content (Compare NMR Peaks page)
    return render_template_string(COMPARE_PAGE)

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


# HTML content for each page (moved from separate files or defined here)

INDEX_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NMR Structure Database - Add/Edit</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f3f4f6;
            color: #333;
        }
        .container {
            max-width: 1200px;
        }
        textarea {
            min-height: 120px;
            font-family: monospace;
        }
        .animate-spin {
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .modal-content {
            background-color: white;
            padding: 2rem;
            border-radius: 0.5rem;
            max-width: 90%;
            max-height: 90vh;
            overflow-y: auto;
            width: 800px;
        }
        .loading-spinner {
            display: none;
        }
        .loading .loading-spinner {
            display: inline-block;
        }
        #imagePreview {
            display: none;
        }
        #imagePreview img {
            max-height: 100%;
            width: auto;
            max-width: 100%;
        }
        .nav-link {
            color: #4b5563;
            padding: 0.5rem 1rem;
            border-radius: 0.375rem;
            font-weight: 500;
            font-size: 0.875rem;
        }
        .nav-link:hover {
            color: #3730a3;
            background-color: #e0e7ff;
        }
        .active-nav-link {
            color: #3730a3;
            background-color: #e0e7ff;
        }
    </style>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen">
    <div class="flex flex-col min-h-screen">
        <nav class="bg-white shadow-md">
            <div class="container mx-auto px-4 py-4 flex justify-between items-center">
                <a href="/" class="text-2xl font-extrabold text-indigo-700">NMR Structure Database</a>
                <div class="flex space-x-4">
                    <a href="/" class="nav-link active-nav-link">Add/Edit Structure</a>
                    <a href="/structures.html" class="nav-link">View Structures</a>
                    <a href="/analysis.html" class="nav-link">NMR Analysis</a>
                    <a href="/compare.html" class="nav-link">Compare NMR Peaks</a>
                </div>
            </div>
        </nav>

        <main class="flex-grow container mx-auto p-4 sm:p-6 lg:p-8">
            <h1 class="text-3xl font-bold text-gray-800 mb-6">Add/Edit NMR Structure</h1>

            <div id="message" class="hidden bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mb-6" role="alert">
                <p id="message-text" class="font-bold"></p>
            </div>
            <div id="error-message" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-6" role="alert">
                <p id="error-message-text" class="font-bold"></p>
            </div>

            <div class="bg-white p-6 rounded-lg shadow-md mb-8">
                <button id="toggleFormBtn" class="bg-indigo-600 text-white font-bold py-3 px-6 rounded-lg shadow-lg hover:bg-indigo-700 transition duration-300 flex items-center justify-center w-full">
                    <svg id="plusIcon" xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                    </svg>
                    <svg id="minusIcon" xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 mr-2 hidden" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 12H6" />
                    </svg>
                    <span id="buttonText">Add New Structure</span>
                </button>

                <form id="nmrEntryForm" class="space-y-6 mt-6 hidden">
                    <input type="hidden" id="entryId">
                    
                    <div>
                        <label for="nameInput" class="block text-sm font-medium text-gray-700">Structure Name *</label>
                        <input type="text" id="nameInput" required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>

                    <div class="mb-6"> 
                        <label class="block text-sm font-medium text-gray-700">Structure Image</label>
                        <div class="mt-2 flex items-center">
                            <label for="imageUpload" class="cursor-pointer bg-white py-2 px-3 border border-gray-300 rounded-md shadow-sm text-sm leading-4 font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                                Choose Image
                            </label>
                            <span id="imageFileName" class="ml-2 text-sm text-gray-500">No image selected</span>
                        </div>
                        <input type="file" id="imageUpload" accept="image/*" class="hidden">
                        <div id="imagePreview" class="mt-2">
                            <img id="previewImage" class="max-h-40 rounded border border-gray-200">
                        </div>
                        <input type="hidden" id="structureImage">
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                            <label for="hsqcPeaks" class="block text-sm font-medium text-gray-700">HSQC Peaks (1H, 13C)</label>
                            <textarea id="hsqcPeaks" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16&#10;5.12 101.3&#10;..."></textarea>
                            <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift (one peak per line)</p>
                        </div>
                        <div>
                            <label for="cosyPeaks" class="block text-sm font-medium text-gray-700">COSY Peaks (1H, 1H)</label>
                            <textarea id="cosyPeaks" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 7.26&#10;5.12 3.45&#10;..."></textarea>
                            <p class="text-xs text-gray-500 mt-1">Format: 1H_shift1 1H_shift2 (one peak per line)</p>
                        </div>
                        <div>
                            <label for="hmbcPeaks" class="block text-sm font-medium text-gray-700">HMBC Peaks (1H, 13C)</label>
                            <textarea id="hmbcPeaks" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16&#10;5.12 101.3&#10;..."></textarea>
                            <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift (one peak per line)</p>
                        </div>
                    </div>

                    <div class="flex justify-end space-x-2">
                        <button type="button" onclick="clearForm()" class="bg-gray-300 text-gray-800 py-2 px-4 rounded-md hover:bg-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2">
                            Clear Form
                        </button>
                        <button type="submit" class="bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 flex items-center">
                            <span id="submitText">Save Structure</span>
                            <span id="submitSpinner" class="loading-spinner ml-2 animate-spin inline-block w-4 h-4 border-2 border-t-2 border-t-white border-indigo-200 rounded-full"></span>
                        </button>
                    </div>
                </form>
            </div>
        </main>

        <footer class="bg-gray-800 text-white text-center p-4">
            <p>&copy; 2023 NMR Structure Database. All rights reserved.</p>
        </footer>
    </div>

    <script>
        const API_BASE_URL = '/api/entries';
        
        // DOM Elements
        const nmrEntryForm = document.getElementById('nmrEntryForm');
        const toggleFormBtn = document.getElementById('toggleFormBtn');
        const plusIcon = document.getElementById('plusIcon');
        const minusIcon = document.getElementById('minusIcon');
        const buttonText = document.getElementById('buttonText');
        const submitBtn = document.querySelector('#nmrEntryForm button[type="submit"]');
        const submitSpinner = document.getElementById('submitSpinner');
        const submitText = document.getElementById('submitText');
        const imageUpload = document.getElementById('imageUpload');
        const imageFileName = document.getElementById('imageFileName');
        const imagePreview = document.getElementById('imagePreview');
        const previewImage = document.getElementById('previewImage');

        // Form elements
        const entryIdInput = document.getElementById('entryId');
        const nameInput = document.getElementById('nameInput');
        const hsqcPeaks = document.getElementById('hsqcPeaks');
        const cosyPeaks = document.getElementById('cosyPeaks');
        const hmbcPeaks = document.getElementById('hmbcPeaks');
        const structureImage = document.getElementById('structureImage');

        // Image upload handler
        imageUpload.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (!file) return;

            // Validate file size (max 2MB)
            if (file.size > 2 * 1024 * 1024) {
                showMessage('Image size must be less than 2MB', true);
                return;
            }

            imageFileName.textContent = file.name;
            
            const reader = new FileReader();
            reader.onload = function(event) {
                previewImage.src = event.target.result;
                imagePreview.style.display = 'block';
                structureImage.value = event.target.result;
            };
            
            if (file.type.match('image.*')) {
                reader.readAsDataURL(file);
            } else {
                showMessage('Please select an image file (JPG, PNG, GIF)', true);
            }
        });

        // Toggle form visibility
        toggleFormBtn.addEventListener('click', () => {
            nmrEntryForm.classList.toggle('hidden');
            plusIcon.classList.toggle('hidden');
            minusIcon.classList.toggle('hidden');
            buttonText.textContent = nmrEntryForm.classList.contains('hidden') ? 'Add New Structure' : 'Hide Form';
        });

        function loadStructureForEdit(structureId) {
            fetch(`${API_BASE_URL}/${structureId}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(result => {
                    populateFormForEdit(result);
                    nmrEntryForm.classList.remove('hidden');
                    plusIcon.classList.add('hidden');
                    minusIcon.classList.remove('hidden');
                    buttonText.textContent = 'Hide Form';
                })
                .catch(error => {
                    showMessage(`Error loading structure: ${error.message}`, true);
                    console.error("Error loading structure:", error);
                });
        }

        function populateFormForEdit(structureData) {
            entryIdInput.value = structureData._id || '';
            nameInput.value = structureData.name || '';
            
            hsqcPeaks.value = (Array.isArray(structureData.hsqc_peaks)
                ? structureData.hsqc_peaks.map(p => p.join(' ')).join('\n')
                : structureData.hsqc_peaks || '');
            
            cosyPeaks.value = (Array.isArray(structureData.cosy_peaks)
                ? structureData.cosy_peaks.map(p => p.join(' ')).join('\n')
                : structureData.cosy_peaks || '');
            
            hmbcPeaks.value = (Array.isArray(structureData.hmbc_peaks)
                ? structureData.hmbc_peaks.map(p => p.join(' ')).join('\n')
                : structureData.hmbc_peaks || '');
            
            structureImage.value = structureData.structure_image_base64 || '';
            imageFileName.textContent = structureData.structure_image_base64 ? 'Uploaded image' : 'No image selected';
            
            previewImage.src = structureData.structure_image_base64 || '';
            imagePreview.style.display = structureData.structure_image_base64 ? 'block' : 'none';
        }

        function clearForm() {
            entryIdInput.value = '';
            nameInput.value = '';
            hsqcPeaks.value = '';
            cosyPeaks.value = '';
            hmbcPeaks.value = '';
            structureImage.value = '';
            imageUpload.value = '';
            imageFileName.textContent = 'No image selected';
            imagePreview.style.display = 'none';
        }

        function deleteStructure(structureId) {
            if (!confirm(`Are you sure you want to delete structure ID ${structureId}?`)) {
                return;
            }
            
            fetch(`${API_BASE_URL}/${structureId}`, {
                method: 'DELETE'
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(result => {
                if (result.success) {
                    showMessage(result.message || 'Structure deleted successfully');
                } else {
                    throw new Error(result.error || 'Failed to delete structure');
                }
            })
            .catch(error => {
                    showMessage(`Error deleting structure: ${error.message}`, true);
                    console.error("Error deleting structure:", error);
                });
        }

        // Form submission
        nmrEntryForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            if (!nameInput.value.trim()) {
                showMessage('Structure name is required', true);
                return;
            }

            const formData = {
                name: nameInput.value.trim(),
                hsqc_peaks: hsqcPeaks.value.trim(),
                cosy_peaks: cosyPeaks.value.trim(),
                hmbc_peaks: hmbcPeaks.value.trim(),
                structure_image_base64: structureImage.value.trim()
            };

            // If we have an ID, we're updating an existing entry
            const entryId = entryIdInput.value;
            const method = entryId ? 'PUT' : 'POST';
            const url = entryId ? `${API_BASE_URL}/${entryId}` : API_BASE_URL;

            try {
                // Show loading state
                submitBtn.disabled = true;
                submitSpinner.classList.remove('loading-spinner');
                submitText.textContent = entryId ? 'Updating...' : 'Saving...';

                const response = await fetch(url, {
                    method,
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(formData)
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Request failed');
                }

                if (result.success) {
                    showMessage(result.message || (entryId ? 'Structure updated successfully' : 'Structure added successfully'));
                    clearForm();
                    if (!entryId) {
                        // If this was a new entry, update the ID field for potential edits
                        entryIdInput.value = result.data?.id || '';
                    }
                } else {
                    throw new Error(result.error || 'Operation failed');
                }
            } catch (error) {
                showMessage(`Error: ${error.message}`, true);
                console.error("Error submitting form:", error);
            } finally {
                // Reset button state
                submitBtn.disabled = false;
                submitSpinner.classList.add('loading-spinner');
                submitText.textContent = entryId ? 'Update Structure' : 'Save Structure';
            }
        });

        function showMessage(message, isError = false) {
            const messageDiv = isError ? document.getElementById('error-message') : document.getElementById('message');
            const textSpan = isError ? document.getElementById('error-message-text') : document.getElementById('message-text');
            
            textSpan.textContent = message;
            messageDiv.classList.remove('hidden');
            
            // Auto-hide after 5 seconds
            setTimeout(() => {
                messageDiv.classList.add('hidden');
            }, 5000);
        }

        // Initialize the page
        document.addEventListener('DOMContentLoaded', () => {
            // Check for edit ID in URL
            const urlParams = new URLSearchParams(window.location.search);
            const editId = urlParams.get('editId');
            
            if (editId) {
                loadStructureForEdit(editId);
                nmrEntryForm.classList.remove('hidden');
                plusIcon.classList.add('hidden');
                minusIcon.classList.remove('hidden');
                buttonText.textContent = 'Hide Form';
            }
            
            // Hide image preview initially
            imagePreview.style.display = 'none';
        });
    </script>
</body>
</html>
"""

STRUCTURES_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NMR Structures</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f3f4f6;
            color: #333;
        }
        .container {
            max-width: 1200px;
        }
        .animate-spin {
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .peak-list {
            list-style: none;
            padding: 0;
            margin: 0;
            background-color: #f8f8f8;
            border-radius: 0.375rem;
            padding: 1rem;
            max-height: 200px; /* Adjust as needed */
            overflow-y: auto;
            border: 1px solid #e5e7eb;
        }
        .loading-spinner {
            display: none;
        }
        .loading .loading-spinner {
            display: inline-block;
        }
    </style>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen">
    <div class="container mx-auto p-4 sm:p-6 lg:p-8">
        <h1 class="text-4xl font-extrabold text-center text-gray-900 mb-10">NMR Structure Database</h1>

        <div class="flex justify-center mb-8">
            <a href="/" class="bg-indigo-600 text-white font-bold py-3 px-6 rounded-lg shadow-lg hover:bg-indigo-700 transition duration-300 mx-2 flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                </svg>
                Add/Edit Structures
            </a>
            <a href="/structures.html" class="bg-gray-700 text-white font-bold py-3 px-6 rounded-lg shadow-lg hover:bg-gray-800 transition duration-300 mx-2 flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                </svg>
                View/Search Structures
            </a>
            <a href="/analysis.html" class="bg-teal-600 text-white font-bold py-3 px-6 rounded-lg shadow-lg hover:bg-teal-700 transition duration-300 mx-2 flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 21h18" />
                </svg>
                Analyze NMR Data
            </a>
        </div>

        <div class="bg-white p-6 rounded-lg shadow-md mb-8">
            <h2 class="text-2xl font-bold text-gray-800 mb-4">Search Structures</h2>
            <div id="resultsMessage" class="hidden bg-blue-100 border border-blue-400 text-blue-700 px-4 py-3 rounded relative mb-4" role="alert">
                <span class="block sm:inline" id="resultsMessageText"></span>
                <span class="absolute top-0 bottom-0 right-0 px-4 py-3 cursor-pointer" onclick="document.getElementById('resultsMessage').classList.add('hidden')">
                    <svg class="fill-current h-6 w-6 text-blue-500" role="button" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><title>Close</title><path d="M14.348 14.849a1.2 1.2 0 0 1-1.697 0L10 11.819l-2.651 3.029a1.2 1.2 0 1 1-1.697-1.697l2.758-3.15-2.759-3.15a1.2 1.2 0 1 1 1.697-1.697L10 8.183l2.651-3.031a1.2 1.2 0 1 1 1.697 1.697L11.819 10l3.029 2.651a1.2 1.2 0 0 1 0 1.698z"/></svg>
                </span>
            </div>
            
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                    <label for="nameSearchInput" class="block text-sm font-medium text-gray-700">Search by Name</label>
                    <input type="text" id="nameSearchInput" placeholder="Enter structure name" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-700">Search by Peak</label>
                    <div class="mt-1 flex items-center space-x-2">
                        <input type="text" id="peakSearchInput1" placeholder="1H Shift" class="flex-1 rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                        <input type="text" id="peakSearchInput2" placeholder="13C Shift (HSQC/HMBC)" class="flex-1 rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                </div>
            </div>
            <div class="mb-6">
                <label class="block text-sm font-medium text-gray-700">Peak Type</label>
                <div class="mt-1 flex space-x-4">
                    <label class="inline-flex items-center">
                        <input type="radio" name="peakType" value="all" checked class="form-radio text-indigo-600">
                        <span class="ml-2 text-gray-700">All</span>
                    </label>
                    <label class="inline-flex items-center">
                        <input type="radio" name="peakType" value="hsqc" class="form-radio text-indigo-600">
                        <span class="ml-2 text-gray-700">HSQC</span>
                    </label>
                    <label class="inline-flex items-center">
                        <input type="radio" name="peakType" value="cosy" class="form-radio text-indigo-600">
                        <span class="ml-2 text-gray-700">COSY</span>
                    </label>
                    <label class="inline-flex items-center">
                        <input type="radio" name="peakType" value="hmbc" class="form-radio text-indigo-600">
                        <span class="ml-2 text-gray-700">HMBC</span>
                    </label>
                </div>
            </div>
            <div class="flex justify-end space-x-2">
                <button id="clearSearchButton" class="bg-gray-300 text-gray-800 py-2 px-4 rounded-md hover:bg-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2">
                    Clear Filters
                </button>
                <button id="searchButton" class="bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 flex items-center">
                    Search
                    <span id="searchSpinner" class="loading-spinner ml-2 animate-spin inline-block w-4 h-4 border-2 border-t-2 border-t-white border-indigo-200 rounded-full"></span>
                </button>
            </div>
        </div>

        <div id="structuresContainer" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            </div>

        <div id="noResults" class="hidden text-center text-gray-600 mt-8">
            <p class="text-lg">No structures found matching your criteria.</p>
        </div>
    </div>

    <script>
        const API_BASE_URL = '/api/entries';

        // DOM Elements
        const structuresContainer = document.getElementById('structuresContainer');
        const noResultsMessage = document.getElementById('noResults');
        const searchButton = document.getElementById('searchButton');
        const clearSearchButton = document.getElementById('clearSearchButton');
        const nameSearchInput = document.getElementById('nameSearchInput');
        const peakSearchInput1 = document.getElementById('peakSearchInput1');
        const peakSearchInput2 = document.getElementById('peakSearchInput2');
        const peakTypeRadios = document.querySelectorAll('input[name="peakType"]');
        const searchSpinner = document.getElementById('searchSpinner');
        const resultsMessageDiv = document.getElementById('resultsMessage');
        const resultsMessageText = document.getElementById('resultsMessageText');

        // Function to show/hide loading spinner
        function showLoading(isLoading) {
            if (isLoading) {
                searchButton.classList.add('loading');
                searchButton.disabled = true;
            } else {
                searchButton.classList.remove('loading');
                searchButton.disabled = false;
            }
        }

        function showResultsMessage(message, isError = false) {
            resultsMessageText.textContent = message;
            resultsMessageDiv.classList.remove('hidden');
            if (isError) {
                resultsMessageDiv.classList.remove('bg-blue-100', 'border-blue-400', 'text-blue-700');
                resultsMessageDiv.classList.add('bg-red-100', 'border-red-400', 'text-red-700');
            } else {
                resultsMessageDiv.classList.remove('bg-red-100', 'border-red-400', 'text-blue-700');
                resultsMessageDiv.classList.add('bg-blue-100', 'border-blue-400', 'text-blue-700');
            }
            setTimeout(() => {
                resultsMessageDiv.classList.add('hidden');
            }, 5000);
        }

        // Helper function to format peaks for display
        function formatPeaks(peaks) {
            if (!peaks || peaks.length === 0) return 'N/A';
            if (typeof peaks === 'string') return peaks; // If it's somehow already a string

            // Handles array of arrays (tuples) like [[1.2, 4.5], [6.7, 8.9]]
            return peaks.map(peak => {
                if (Array.isArray(peak)) {
                    // Assuming peak is [H_shift, C_shift] or [H1_shift, H2_shift]
                    return peak.map(val => val.toFixed(2)).join(' '); // Format to 2 decimal places
                }
                return peak.toFixed(2); // For single float peaks, though not currently used this way
            }).join('\n'); // Join each peak pair with a newline
        }

        async function fetchEntries(peakSearch1 = '', peakSearch2 = '', peakType = 'all', nameSearchTerm = '') {
            showLoading(true);
            structuresContainer.innerHTML = ''; // Clear previous results
            noResultsMessage.classList.add('hidden'); // Hide no results message initially
            resultsMessageDiv.classList.add('hidden'); // Hide any previous messages

            let url = `${API_BASE_URL}?`;
            const params = [];

            if (nameSearchTerm) {
                params.push(`name=${encodeURIComponent(nameSearchTerm)}`);
            }
            if (peakSearch1) {
                params.push(`hShift=${encodeURIComponent(peakSearch1)}`);
            }
            if (peakSearch2) {
                // Determine if it's cShift or h2Shift based on peakType
                if (peakType === 'cosy') {
                    params.push(`h2Shift=${encodeURIComponent(peakSearch2)}`);
                } else { // hsqc, hmbc, or all
                    params.push(`cShift=${encodeURIComponent(peakSearch2)}`);
                }
            }
            if (peakType && peakType !== 'all') { // Only include peakType if it's not 'all'
                params.push(`peakType=${encodeURIComponent(peakType)}`);
            }

            url += params.join('&');
            console.log("Fetching from URL:", url); // Debugging

            try {
                const response = await fetch(url);
                if (!response.ok) {
                    // If response is not OK, it might still return JSON with an error message
                    const errorData = await response.json();
                    throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                }
                const entries = await response.json(); // Expect a direct array response or an error object

                console.log("Received entries:", entries); // Debugging

                if (!Array.isArray(entries)) { // If it's not an array, it's an unexpected format or an error
                    throw new Error(entries.error || 'Unexpected response format');
                }

                if (entries.length === 0) {
                    noResultsMessage.classList.remove('hidden');
                } else {
                    structuresContainer.innerHTML = entries.map(entry => `
                        <div class="bg-white rounded-lg shadow-md overflow-hidden flex flex-col">
                            ${entry.structure_image_base64 ? `
                                <img src="${entry.structure_image_base64}" alt="Structure Image" class="w-full h-48 object-contain bg-gray-100 p-2">
                            ` : `
                                <div class="w-full h-48 bg-gray-200 flex items-center justify-center text-gray-500">No Image</div>
                            `}
                            <div class="p-4 flex-grow flex flex-col">
                                <h3 class="text-xl font-bold mb-2">${entry.name || 'Unnamed Structure'}</h3>
                                <p class="text-sm text-gray-600 mb-4">ID: ${entry._id}</p>
                                
                                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm flex-grow">
                                    <div>
                                        <h4 class="font-semibold mb-1 text-gray-700">HSQC Peaks (1H, 13C)</h4>
                                        <pre class="peak-list">${formatPeaks(entry.hsqc_peaks)}</pre>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold mb-1 text-gray-700">COSY Peaks (1H, 1H)</h4>
                                        <pre class="peak-list">${formatPeaks(entry.cosy_peaks)}</pre>
                                    </div>
                                    <div>
                                        <h4 class="font-semibold mb-1 text-gray-700">HMBC Peaks (1H, 13C)</h4>
                                        <pre class="peak-list">${formatPeaks(entry.hmbc_peaks)}</pre>
                                    </div>
                                </div>

                                <div class="mt-4 flex space-x-2 justify-end">
                                    <a href="/?editId=${entry._id}" class="bg-blue-500 text-white px-4 py-2 rounded-md hover:bg-blue-600 transition duration-300 text-sm">
                                        Edit
                                    </a>
                                    <button onclick="deleteEntry('${entry._id}')" class="bg-red-500 text-white px-4 py-2 rounded-md hover:bg-red-600 transition duration-300 text-sm">
                                        Delete
                                    </button>
                                </div>
                            </div>
                        </div>
                    `).join('');
                }
            } catch (error) {
                console.error("Error fetching entries:", error);
                showResultsMessage(`Error fetching entries: ${error.message}`, true);
                noResultsMessage.classList.remove('hidden'); // Show no results on error too
                noResultsMessage.innerHTML = `<p class="text-lg text-red-600">Error loading structures. Please try again.</p>`;
            } finally {
                showLoading(false);
            }
        }

        async function deleteEntry(id) {
            if (!confirm(`Are you sure you want to delete structure ID ${id}?`)) {
                return;
            }
            try {
                showLoading(true);
                const response = await fetch(`${API_BASE_URL}/${id}`, {
                    method: 'DELETE'
                });
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(result.error || 'Failed to delete entry');
                }
                showResultsMessage(result.message || 'Entry deleted successfully');
                fetchEntries(
                    peakSearchInput1.value.trim(), 
                    peakSearchInput2.value.trim(), 
                    document.querySelector('input[name="peakType"]:checked').value, 
                    nameSearchInput.value.trim()
                ); // Refresh the list
            } catch (error) {
                console.error("Error deleting entry:", error);
                showResultsMessage(`Error deleting entry: ${error.message}`, true);
            } finally {
                showLoading(false);
            }
        }

        // Event Listeners
        searchButton.addEventListener('click', () => {
            const peakSearchTerm1 = peakSearchInput1.value.trim();
            const peakSearchTerm2 = peakSearchInput2.value.trim();
            const nameSearchTerm = nameSearchInput.value.trim();
            const peakType = document.querySelector('input[name="peakType"]:checked').value;
            fetchEntries(peakSearchTerm1, peakSearchTerm2, peakType, nameSearchTerm);
        });

        clearSearchButton.addEventListener('click', () => {
            nameSearchInput.value = '';
            peakSearchInput1.value = '';
            peakSearchInput2.value = '';
            document.querySelector('input[name="peakType"][value="all"]').checked = true;
            document.querySelector('input[name="peakType"][value="all"]').dispatchEvent(new Event('change')); // Trigger change to update inputs
            fetchEntries();
        });

        // Event listener for peak type radio buttons to adjust placeholders
        peakTypeRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                const selectedType = document.querySelector('input[name="peakType"]:checked').value;
                if (selectedType === 'hsqc' || selectedType === 'hmbc') {
                    peakSearchInput1.placeholder = '1H Shift';
                    peakSearchInput2.placeholder = '13C Shift';
                    peakSearchInput2.classList.remove('hidden'); // Ensure it's visible
                } else if (selectedType === 'cosy') {
                    peakSearchInput1.placeholder = '1H Shift 1';
                    peakSearchInput2.placeholder = '1H Shift 2';
                    peakSearchInput2.classList.remove('hidden'); // Ensure it's visible
                } else { // 'all'
                    peakSearchInput1.placeholder = 'Peak Shift (e.g., 7.26)'; // A general hint
                    peakSearchInput2.value = ''; // Clear second input
                    peakSearchInput2.classList.add('hidden'); // Hide second input
                }
            });
        });

        // Keypress listeners for enter key
        nameSearchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchButton.click();
        });
        peakSearchInput1.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchButton.click();
        });
        peakSearchInput2.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchButton.click();
        });

        // Initial Load
        document.addEventListener('DOMContentLoaded', () => {
            // Set initial state of peak search inputs
            document.querySelector('input[name="peakType"]:checked').dispatchEvent(new Event('change'));
            fetchEntries();
        });
    </script>
</body>
</html>
"""

ANALYSIS_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NMR Analysis</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f3f4f6;
            color: #333;
        }
        .container {
            max-width: 1200px;
        }
        textarea {
            min-height: 120px;
            font-family: monospace;
        }
        .animate-spin {
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .nav-link {
            color: #4b5563;
            padding: 0.5rem 1rem;
            border-radius: 0.375rem;
            font-weight: 500;
            font-size: 0.875rem;
        }
        .nav-link:hover {
            color: #3730a3;
            background-color: #e0e7ff;
        }
        .active-nav-link {
            color: #3730a3;
            background-color: #e0e7ff;
        }
        .loading-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(255, 255, 255, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            flex-direction: column;
        }
        .loading-spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #3498db;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
        }
        .plot-container img {
            max-width: 100%;
            height: auto;
            border-radius: 0.5rem;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
    </style>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen">
    <div class="flex flex-col min-h-screen">
        <nav class="bg-white shadow-md">
            <div class="container mx-auto px-4 py-4 flex justify-between items-center">
                <a href="/" class="text-2xl font-extrabold text-indigo-700">NMR Structure Database</a>
                <div class="flex space-x-4">
                    <a href="/" class="nav-link">Add/Edit Structure</a>
                    <a href="/structures.html" class="nav-link">View Structures</a>
                    <a href="/analysis.html" class="nav-link active-nav-link">NMR Analysis</a>
                    <a href="/compare.html" class="nav-link">Compare NMR Peaks</a>
                </div>
            </div>
        </nav>

        <main class="flex-grow container mx-auto p-4 sm:p-6 lg:p-8">
            <h1 class="text-3xl font-bold text-gray-800 mb-6">NMR Analysis</h1>

            <div id="message" class="hidden bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mb-6" role="alert">
                <p id="message-text" class="font-bold"></p>
            </div>
            <div id="error-message" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-6" role="alert">
                <p id="error-message-text" class="font-bold"></p>
            </div>

            <div class="bg-white p-6 rounded-lg shadow-md mb-8">
                <form id="analysisForm" class="space-y-6">
                    <p class="text-gray-700 mb-4">Enter your experimental NMR peak data below. You can provide HSQC, COSY, and HMBC data. The system will analyze it against the stored database structures.</p>
                    
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                            <label for="hsqcData" class="block text-sm font-medium text-gray-700">HSQC Peaks (1H, 13C, Intensity)</label>
                            <textarea id="hsqcData" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16 1.0&#10;5.12 101.3 0.8&#10;..."></textarea>
                            <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift Intensity (one peak per line)</p>
                        </div>
                        <div>
                            <label for="cosyData" class="block text-sm font-medium text-gray-700">COSY Peaks (1H, 1H, Intensity)</label>
                            <textarea id="cosyData" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 7.26 1.0&#10;5.12 3.45 0.5&#10;..."></textarea>
                            <p class="text-xs text-gray-500 mt-1">Format: 1H_shift1 1H_shift2 Intensity (one peak per line)</p>
                        </div>
                        <div>
                            <label for="hmbcData" class="block text-sm font-medium text-gray-700">HMBC Peaks (1H, 13C, Intensity)</label>
                            <textarea id="hmbcData" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16 1.0&#10;5.12 101.3 0.7&#10;..."></textarea>
                            <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift Intensity (one peak per line)</p>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label for="toleranceH" class="block text-sm font-medium text-gray-700">1H Tolerance (ppm)</label>
                            <input type="number" id="toleranceH" value="0.05" step="0.01" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                        </div>
                        <div>
                            <label for="toleranceC" class="block text-sm font-medium text-gray-700">13C Tolerance (ppm)</label>
                            <input type="number" id="toleranceC" value="0.50" step="0.01" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                        </div>
                    </div>

                    <div class="flex justify-end space-x-2">
                        <button type="button" onclick="clearAnalysisForm()" class="bg-gray-300 text-gray-800 py-2 px-4 rounded-md hover:bg-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2">
                            Clear Form
                        </button>
                        <button type="submit" id="analyzeBtn" class="bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 flex items-center">
                            Analyze NMR Data
                            <span id="analyzeSpinner" class="loading-spinner ml-2 animate-spin inline-block w-4 h-4 border-2 border-t-2 border-t-white border-indigo-200 rounded-full hidden"></span>
                        </button>
                    </div>
                </form>
            </div>

            <div id="analysisResults" class="bg-white p-6 rounded-lg shadow-md hidden">
                <h2 class="text-2xl font-bold text-gray-800 mb-4">Analysis Results</h2>
                
                <div id="detectedCompounds" class="mb-6">
                    <h3 class="text-xl font-semibold text-gray-700 mb-3">Detected Compounds</h3>
                    <div id="compoundsList" class="space-y-4">
                        <!-- Detected compounds will be listed here -->
                    </div>
                    <p id="noCompoundsDetected" class="text-gray-600 mt-2 hidden">No compounds detected above the threshold.</p>
                </div>

                <div id="unmatchedPeaks" class="mb-6">
                    <h3 class="text-xl font-semibold text-gray-700 mb-3">Unmatched Sample Peaks</h3>
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                            <h4 class="font-semibold mb-1 text-gray-700">HSQC Unmatched</h4>
                            <pre id="unmatchedHsqc" class="peak-list bg-gray-100"></pre>
                        </div>
                        <div>
                            <h4 class="font-semibold mb-1 text-gray-700">COSY Unmatched</h4>
                            <pre id="unmatchedCosy" class="peak-list bg-gray-100"></pre>
                        </div>
                        <div>
                            <h4 class="font-semibold mb-1 text-gray-700">HMBC Unmatched</h4>
                            <pre id="unmatchedHmbc" class="peak-list bg-gray-100"></pre>
                        </div>
                    </div>
                </div>

                <div id="nmrPlots" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-6">
                    <div class="plot-container">
                        <h3 class="text-xl font-semibold text-gray-700 mb-3 text-center">HSQC Plot</h3>
                        <img id="hsqcPlot" src="" alt="HSQC Plot">
                    </div>
                    <div class="plot-container">
                        <h3 class="text-xl font-semibold text-gray-700 mb-3 text-center">COSY Plot</h3>
                        <img id="cosyPlot" src="" alt="COSY Plot">
                    </div>
                    <div class="plot-container">
                        <h3 class="text-xl font-semibold text-gray-700 mb-3 text-center">HMBC Plot</h3>
                        <img id="hmbcPlot" src="" alt="HMBC Plot">
                    </div>
                </div>
            </div>
            <div id="loadingOverlay" class="loading-overlay hidden">
                <div class="loading-spinner"></div>
                <p class="mt-4 text-lg text-gray-700">Analyzing NMR data...</p>
            </div>
        </main>

        <footer class="bg-gray-800 text-white text-center p-4">
            <p>&copy; 2023 NMR Structure Database. All rights reserved.</p>
        </footer>
    </div>

    <script>
        const API_ANALYZE_URL = '/api/analyze';

        // DOM Elements
        const analysisForm = document.getElementById('analysisForm');
        const hsqcDataInput = document.getElementById('hsqcData');
        const cosyDataInput = document.getElementById('cosyData');
        const hmbcDataInput = document.getElementById('hmbcData');
        const toleranceHInput = document.getElementById('toleranceH');
        const toleranceCInput = document.getElementById('toleranceC');
        const analyzeBtn = document.getElementById('analyzeBtn');
        const analyzeSpinner = document.getElementById('analyzeSpinner');
        const analysisResultsDiv = document.getElementById('analysisResults');
        const compoundsListDiv = document.getElementById('compoundsList');
        const noCompoundsDetectedP = document.getElementById('noCompoundsDetected');
        const unmatchedHsqcPre = document.getElementById('unmatchedHsqc');
        const unmatchedCosyPre = document.getElementById('unmatchedCosy');
        const unmatchedHmbcPre = document.getElementById('unmatchedHmbc');
        const hsqcPlotImg = document.getElementById('hsqcPlot');
        const cosyPlotImg = document.getElementById('cosyPlot');
        const hmbcPlotImg = document.getElementById('hmbcPlot');
        const loadingOverlay = document.getElementById('loadingOverlay');

        function showMessage(message, isError = false) {
            const messageDiv = isError ? document.getElementById('error-message') : document.getElementById('message');
            const textSpan = isError ? document.getElementById('error-message-text') : document.getElementById('message-text');
            
            textSpan.textContent = message;
            messageDiv.classList.remove('hidden');
            
            setTimeout(() => {
                messageDiv.classList.add('hidden');
            }, 5000);
        }

        function clearAnalysisForm() {
            hsqcDataInput.value = '';
            cosyDataInput.value = '';
            hmbcDataInput.value = '';
            toleranceHInput.value = '0.05';
            toleranceCInput.value = '0.50';
            analysisResultsDiv.classList.add('hidden');
            compoundsListDiv.innerHTML = '';
            unmatchedHsqcPre.textContent = '';
            unmatchedCosyPre.textContent = '';
            unmatchedHmbcPre.textContent = '';
            hsqcPlotImg.src = '';
            cosyPlotImg.src = '';
            hmbcPlotImg.src = '';
            noCompoundsDetectedP.classList.add('hidden');
        }

        analysisForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const hsqcData = hsqcDataInput.value.trim();
            const cosyData = cosyDataInput.value.trim();
            const hmbcData = hmbcDataInput.value.trim();
            const toleranceH = parseFloat(toleranceHInput.value);
            const toleranceC = parseFloat(toleranceCInput.value);

            if (!hsqcData && !cosyData && !hmbcData) {
                showMessage('Please enter at least one type of NMR data for analysis.', true);
                return;
            }

            try {
                analyzeBtn.disabled = true;
                analyzeSpinner.classList.remove('hidden');
                loadingOverlay.classList.remove('hidden');
                analysisResultsDiv.classList.add('hidden'); // Hide previous results

                const response = await fetch(API_ANALYZE_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        hsqc_data: hsqcData,
                        cosy_data: cosyData,
                        hmbc_data: hmbcData,
                        tolerance_h: toleranceH,
                        tolerance_c: toleranceC
                    })
                });

                const result = await response.json();

                if (!response.ok || !result.success) {
                    throw new Error(result.error || 'Failed to perform analysis.');
                }

                displayAnalysisResults(result.detected_entries, result.unmatched_sample_peaks, result.hsqc_image_base64, result.cosy_image_base64, result.hmbc_image_base64);
                showMessage(result.message || 'Analysis completed successfully!');

            } catch (error) {
                showMessage(`Error during analysis: ${error.message}`, true);
                console.error("Analysis error:", error);
            } finally {
                analyzeBtn.disabled = false;
                analyzeSpinner.classList.add('hidden');
                loadingOverlay.classList.add('hidden');
            }
        });

        function displayAnalysisResults(detectedEntries, unmatchedPeaks, hsqcPlotBase64, cosyPlotBase64, hmbcPlotBase64) {
            compoundsListDiv.innerHTML = '';
            if (detectedEntries && detectedEntries.length > 0) {
                noCompoundsDetectedP.classList.add('hidden');
                detectedEntries.forEach(entry => {
                    const compoundDiv = document.createElement('div');
                    compoundDiv.className = 'bg-gray-50 p-4 rounded-md shadow-sm border border-gray-200';
                    compoundDiv.innerHTML = `
                        <h4 class="text-lg font-bold text-indigo-700">${entry.compound.name || 'Unnamed Compound'}</h4>
                        <p class="text-sm text-gray-600">Overall Match Score: <span class="font-semibold">${(entry.match_score * 100).toFixed(2)}%</span></p>
                        <p class="text-sm text-gray-600">HSQC Matches: ${entry.details.hsqc_matches} (${(entry.details.hsqc_percentage * 100).toFixed(2)}%)</p>
                        <p class="text-sm text-gray-600">COSY Matches: ${entry.details.cosy_matches} (${(entry.details.cosy_percentage * 100).toFixed(2)}%)</p>
                        <p class="text-sm text-gray-600">HMBC Matches: ${entry.details.hmbc_matches} (${(entry.details.hmbc_percentage * 100).toFixed(2)}%)</p>
                    `;
                    compoundsListDiv.appendChild(compoundDiv);
                });
            } else {
                noCompoundsDetectedP.classList.remove('hidden');
            }

            unmatchedHsqcPre.textContent = unmatchedPeaks.hsqc.map(p => p.map(val => val.toFixed(2)).join(' ')).join('\n') || 'None';
            unmatchedCosyPre.textContent = unmatchedPeaks.cosy.map(p => p.map(val => val.toFixed(2)).join(' ')).join('\n') || 'None';
            unmatchedHmbcPre.textContent = unmatchedPeaks.hmbc.map(p => p.map(val => val.toFixed(2)).join(' ')).join('\n') || 'None';

            hsqcPlotImg.src = hsqcPlotBase64 ? `data:image/png;base64,${hsqcPlotBase64}` : '';
            cosyPlotImg.src = cosyPlotBase64 ? `data:image/png;base64,${cosyPlotBase64}` : '';
            hmbcPlotImg.src = hmbcPlotBase64 ? `data:image/png;base64,${hmbcPlotBase64}` : '';

            analysisResultsDiv.classList.remove('hidden');
        }

        // Initial setup
        document.addEventListener('DOMContentLoaded', () => {
            clearAnalysisForm(); // Clear form and results on load
        });
    </script>
</body>
</html>
"""

COMPARE_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Compare NMR Peaks</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f3f4f6;
            color: #333;
        }
        .container {
            max-width: 1200px;
        }
        textarea {
            min-height: 120px;
            font-family: monospace;
        }
        .animate-spin {
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .nav-link {
            color: #4b5563;
            padding: 0.5rem 1rem;
            border-radius: 0.375rem;
            font-weight: 500;
            font-size: 0.875rem;
        }
        .nav-link:hover {
            color: #3730a3;
            background-color: #e0e7ff;
        }
        .active-nav-link {
            color: #3730a3;
            background-color: #e0e7ff;
        }
        .results-section {
            background-color: #ffffff;
            padding: 1.5rem;
            border-radius: 0.5rem;
            box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
        }
        .results-list {
            list-style: none;
            padding: 0;
            margin-top: 0.5rem;
        }
        .results-list li {
            padding: 0.5rem 0;
            border-bottom: 1px solid #e5e7eb;
        }
        .results-list li:last-child {
            border-bottom: none;
        }
    </style>
</head>
<body class="bg-gray-50 text-gray-900 min-h-screen">
    <div class="flex flex-col min-h-screen">
        <nav class="bg-white shadow-md">
            <div class="container mx-auto px-4 py-4 flex justify-between items-center">
                <a href="/" class="text-2xl font-extrabold text-indigo-700">NMR Structure Database</a>
                <div class="flex space-x-4">
                    <a href="/" class="nav-link">Add/Edit Structure</a>
                    <a href="/structures.html" class="nav-link">View Structures</a>
                    <a href="/analysis.html" class="nav-link">NMR Analysis</a>
                    <a href="/compare.html" class="nav-link active-nav-link">Compare NMR Peaks</a>
                </div>
            </div>
        </nav>

        <main class="flex-grow container mx-auto p-4 sm:p-6 lg:p-8">
            <h1 class="text-3xl font-bold text-gray-800 mb-6">Compare HSQC Peaks to Database</h1>

            <div id="message" class="hidden bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mb-6" role="alert">
                <p id="message-text" class="font-bold"></p>
            </div>
            <div id="error-message" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-6" role="alert">
                <p id="error-message-text" class="font-bold"></p>
            </div>

            <div class="bg-white p-6 rounded-lg shadow-md mb-8">
                <form id="compareForm" class="space-y-6">
                    <div>
                        <label for="hsqcPeaks" class="block text-sm font-medium text-gray-700">HSQC Peaks (1H, 13C, Intensity)</label>
                        <textarea id="hsqcPeaks" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="3.31 49.1 1.0&#10;7.20 128.0 0.5&#10;..."></textarea>
                        <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift Intensity (one peak per line)</p>
                    </div>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label for="d1h" class="block text-sm font-medium text-gray-700">1H Tolerance (ppm)</label>
                            <input type="number" id="d1h" value="0.06" step="0.01" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                        </div>
                        <div>
                            <label for="d13c" class="block text-sm font-medium text-gray-700">13C Tolerance (ppm)</label>
                            <input type="number" id="d13c" value="0.8" step="0.1" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                        </div>
                    </div>

                    <div class="flex justify-end space-x-2">
                        <button type="submit" id="compareBtn" class="bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 flex items-center">
                            Compare to HMDB/BMRB Database
                            <span id="compareSpinner" class="loading-spinner ml-2 animate-spin inline-block w-4 h-4 border-2 border-t-2 border-t-white border-indigo-200 rounded-full hidden"></span>
                        </button>
                    </div>
                </form>
            </div>

            <div id="comparisonResults" class="results-section hidden">
                <h2 class="text-2xl font-bold text-gray-800 mb-4">Comparison Results</h2>
                
                <div class="mb-6">
                    <h3 class="text-xl font-semibold text-gray-700 mb-2">Fully Matched Compounds (100%)</h3>
                    <ul id="fullyMatchedList" class="results-list">
                        <!-- Fully matched compounds will be listed here -->
                    </ul>
                    <p id="noFullyMatched" class="text-gray-600 mt-2 hidden">No compounds found with 100% peak matches.</p>
                </div>

                <div>
                    <h3 class="text-xl font-semibold text-gray-700 mb-2">Partially Matched Compounds (≥50%)</h3>
                    <ul id="partiallyMatchedList" class="results-list">
                        <!-- Partially matched compounds will be listed here -->
                    </ul>
                    <p id="noPartiallyMatched" class="text-gray-600 mt-2 hidden">No compounds found with ≥50% peak matches.</p>
                </div>
            </div>
        </main>

        <footer class="bg-gray-800 text-white text-center p-4 mt-8">
            <p>&copy; 2023 NMR Structure Database. All rights reserved.</p>
        </footer>
    </div>

    <script>
        const API_COMPARE_URL = '/api/quick-match';

        // DOM Elements
        const compareForm = document.getElementById('compareForm');
        const hsqcPeaksInput = document.getElementById('hsqcPeaks');
        const d1hInput = document.getElementById('d1h');
        const d13cInput = document.getElementById('d13c');
        const compareBtn = document.getElementById('compareBtn');
        const compareSpinner = document.getElementById('compareSpinner');
        const comparisonResultsDiv = document.getElementById('comparisonResults');
        const fullyMatchedList = document.getElementById('fullyMatchedList');
        const partiallyMatchedList = document.getElementById('partiallyMatchedList');
        const noFullyMatched = document.getElementById('noFullyMatched');
        const noPartiallyMatched = document.getElementById('noPartiallyMatched');

        function showMessage(message, isError = false) {
            const messageDiv = isError ? document.getElementById('error-message') : document.getElementById('message');
            const textSpan = isError ? document.getElementById('error-message-text') : document.getElementById('message-text');
            
            textSpan.textContent = message;
            messageDiv.classList.remove('hidden');
            
            setTimeout(() => {
                messageDiv.classList.add('hidden');
            }, 5000);
        }

        compareForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const hsqcPeaks = hsqcPeaksInput.value.trim();
            const d1h = parseFloat(d1hInput.value);
            const d13c = parseFloat(d13cInput.value);

            if (!hsqcPeaks) {
                showMessage('Please enter HSQC peaks for comparison.', true);
                return;
            }

            try {
                compareBtn.disabled = true;
                compareSpinner.classList.remove('hidden');
                comparisonResultsDiv.classList.add('hidden'); // Hide previous results

                const response = await fetch(API_COMPARE_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ hsqcPeaks, d1h, d13c })
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Failed to compare peaks.');
                }

                displayComparisonResults(result);
                showMessage(result.message || 'Comparison completed successfully!');

            } catch (error) {
                showMessage(`Error comparing peaks: ${error.message}`, true);
                console.error("Comparison error:", error);
            } finally {
                compareBtn.disabled = false;
                compareSpinner.classList.add('hidden');
            }
        });

        function displayComparisonResults(results) {
            fullyMatchedList.innerHTML = '';
            partiallyMatchedList.innerHTML = '';
            noFullyMatched.classList.add('hidden');
            noPartiallyMatched.classList.add('hidden');

            if (results.fully && results.fully.length > 0) {
                results.fully.forEach(compoundId => {
                    const li = document.createElement('li');
                    li.textContent = compoundId;
                    fullyMatchedList.appendChild(li);
                });
            } else {
                noFullyMatched.classList.remove('hidden');
            }

            if (results.partial && results.partial.length > 0) {
                results.partial.forEach(match => {
                    const li = document.createElement('li');
                    // match is like ['compoundA', '1/2', '50.00%']
                    li.textContent = `${match[0]} (Matched: ${match[1]}, Percentage: ${match[2]})`;
                    partiallyMatchedList.appendChild(li);
                });
            } else {
                noPartiallyMatched.classList.remove('hidden');
            }

            comparisonResultsDiv.classList.remove('hidden');
        }

        // Initial setup
        document.addEventListener('DOMContentLoaded', () => {
            // You can pre-fill with example peaks if desired
            // hsqcPeaksInput.value = "3.35 49.7 1.0\n7.20 128.1 0.5";
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    # Ensure the database connection is attempted when the app starts
    db_operations.initialize_db_connection()
    app.run(debug=True)
