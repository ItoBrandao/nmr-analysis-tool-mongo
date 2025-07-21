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
        .peak-list li {
            padding: 0.25rem 0;
            border-bottom: 1px dashed #e5e7eb;
        }
        .peak-list li:last-child {
            border-bottom: none;
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
                    <a href="/" class="nav-link">Add/Edit Structure</a>
                    <a href="/structures.html" class="nav-link active-nav-link">View Structures</a>
                    <a href="/analysis.html" class="nav-link">NMR Analysis</a>
                    <a href="/compare.html" class="nav-link">Compare NMR Peaks</a>
                </div>
            </div>
        </nav>

        <main class="flex-grow container mx-auto p-4 sm:p-6 lg:p-8">
            <h1 class="text-3xl font-bold text-gray-800 mb-6">View & Search NMR Structures</h1>

            <div id="message" class="hidden bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mb-6" role="alert">
                <p id="message-text" class="font-bold"></p>
            </div>
            <div id="error-message" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-6" role="alert">
                <p id="error-message-text" class="font-bold"></p>
            </div>

            <div class="bg-white p-6 rounded-lg shadow-md mb-8">
                <h2 class="text-xl font-semibold text-gray-700 mb-4">Search Structures</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div>
                        <label for="nameSearchInput" class="block text-sm font-medium text-gray-700">Search by Name</label>
                        <input type="text" id="nameSearchInput" placeholder="Enter structure name"
                               class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-700">Search by Peak Type</label>
                        <div class="mt-1 flex space-x-4">
                            <label class="inline-flex items-center">
                                <input type="radio" name="peakType" value="all" checked
                                       class="form-radio text-indigo-600 focus:ring-indigo-500" onchange="togglePeakInputs()">
                                <span class="ml-2 text-gray-700">All</span>
                            </label>
                            <label class="inline-flex items-center">
                                <input type="radio" name="peakType" value="hsqc"
                                       class="form-radio text-indigo-600 focus:ring-indigo-500" onchange="togglePeakInputs()">
                                <span class="ml-2 text-gray-700">HSQC</span>
                            </label>
                            <label class="inline-flex items-center">
                                <input type="radio" name="peakType" value="cosy"
                                       class="form-radio text-indigo-600 focus:ring-indigo-500" onchange="togglePeakInputs()">
                                <span class="ml-2 text-gray-700">COSY</span>
                            </label>
                            <label class="inline-flex items-center">
                                <input type="radio" name="peakType" value="hmbc"
                                       class="form-radio text-indigo-600 focus:ring-indigo-500" onchange="togglePeakInputs()">
                                <span class="ml-2 text-gray-700">HMBC</span>
                            </label>
                        </div>
                    </div>
                    <div>
                        <label for="peakSearchInput1" class="block text-sm font-medium text-gray-700">Peak Shift 1</label>
                        <input type="number" step="0.01" id="peakSearchInput1" placeholder="e.g., 7.26"
                               class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                    <div id="peakSearchInput2Container">
                        <label for="peakSearchInput2" class="block text-sm font-medium text-gray-700">Peak Shift 2 (Optional)</label>
                        <input type="number" step="0.01" id="peakSearchInput2" placeholder="e.g., 77.16"
                               class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                </div>
                <button id="searchButton"
                        class="bg-indigo-600 text-white font-bold py-2 px-4 rounded-md shadow-md hover:bg-indigo-700 transition duration-300 flex items-center justify-center">
                    <svg class="animate-spin h-5 w-5 text-white mr-3 hidden" viewBox="0 0 24 24" id="searchSpinner">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Search</span>
                </button>
            </div>

            <div class="bg-white p-6 rounded-lg shadow-md">
                <h2 class="text-xl font-semibold text-gray-700 mb-4">All Structures</h2>
                <div id="structuresList" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    </div>
                <p id="noResultsMessage" class="text-gray-600 text-center py-8 hidden">No structures found matching your criteria.</p>
                <div id="loadingSpinner" class="text-center py-8 hidden">
                    <svg class="animate-spin mx-auto h-8 w-8 text-indigo-500" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <p class="text-indigo-500 mt-2">Loading structures...</p>
                </div>
            </div>
        </main>

        <div id="imageModal" class="modal hidden">
            <div class="modal-content relative">
                <button class="absolute top-2 right-2 text-gray-600 hover:text-gray-900 text-3xl font-bold" onclick="closeImageModal()">&times;</button>
                <img id="modalImage" src="" alt="Structure Image" class="max-w-full max-h-[80vh] mx-auto">
            </div>
        </div>

        <footer class="bg-gray-800 text-white text-center p-4 mt-8">
            <p>&copy; 2023 NMR Structure Database. All rights reserved.</p>
        </footer>
    </div>

    <script>
        const API_BASE_URL = '/api/entries';
        const structuresList = document.getElementById('structuresList');
        const noResultsMessage = document.getElementById('noResultsMessage');
        const loadingSpinner = document.getElementById('loadingSpinner');
        const searchButton = document.getElementById('searchButton');
        const nameSearchInput = document.getElementById('nameSearchInput');
        const peakSearchInput1 = document.getElementById('peakSearchInput1');
        const peakSearchInput2 = document.getElementById('peakSearchInput2');
        const searchSpinner = document.getElementById('searchSpinner');

        // Modal elements
        const imageModal = document.getElementById('imageModal');
        const modalImage = document.getElementById('modalImage');

        function showImageModal(imageUrl) {
            modalImage.src = imageUrl;
            imageModal.classList.remove('hidden');
        }

        function closeImageModal() {
            imageModal.classList.add('hidden');
            modalImage.src = ''; // Clear the image source
        }

        function createStructureCard(structure) {
            const card = document.createElement('div');
            card.className = 'bg-white rounded-lg shadow-lg overflow-hidden flex flex-col';
            card.innerHTML = `
                <div class="p-6 flex-grow">
                    <h3 class="text-xl font-semibold text-gray-800 mb-2">${structure.name}</h3>
                    ${structure.structure_image_base64 ?
                        `<div class="mb-4 flex justify-center items-center bg-gray-100 rounded-md p-2 cursor-pointer" onclick="showImageModal('${structure.structure_image_base64}')">
                            <img src="${structure.structure_image_base64}" alt="${structure.name}" class="max-h-40 max-w-full object-contain">
                        </div>` : ''
                    }
                    <div class="mb-3">
                        <p class="text-sm font-medium text-gray-600">HSQC Peaks:</p>
                        <ul class="peak-list text-sm text-gray-800 mt-1">
                            ${Array.isArray(structure.hsqc_peaks) && structure.hsqc_peaks.length > 0
                                ? structure.hsqc_peaks.map(p => `<li>${p[0]} (1H), ${p[1]} (13C)</li>`).join('')
                                : '<li>No HSQC peaks</li>'}
                        </ul>
                    </div>
                    <div class="mb-3">
                        <p class="text-sm font-medium text-gray-600">COSY Peaks:</p>
                        <ul class="peak-list text-sm text-gray-800 mt-1">
                            ${Array.isArray(structure.cosy_peaks) && structure.cosy_peaks.length > 0
                                ? structure.cosy_peaks.map(p => `<li>${p[0]} (1H), ${p[1]} (1H)</li>`).join('')
                                : '<li>No COSY peaks</li>'}
                        </ul>
                    </div>
                    <div class="mb-3">
                        <p class="text-sm font-medium text-gray-600">HMBC Peaks:</p>
                        <ul class="peak-list text-sm text-gray-800 mt-1">
                            ${Array.isArray(structure.hmbc_peaks) && structure.hmbc_peaks.length > 0
                                ? structure.hmbc_peaks.map(p => `<li>${p[0]} (1H), ${p[1]} (13C)</li>`).join('')
                                : '<li>No HMBC peaks</li>'}
                        </ul>
                    </div>
                </div>
                <div class="bg-gray-50 p-4 border-t border-gray-100 flex justify-end space-x-3">
                    <a href="/?editId=${structure._id}" class="text-indigo-600 hover:text-indigo-900 font-medium text-sm flex items-center">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                        </svg>
                        Edit
                    </a>
                    <button onclick="deleteStructure('${structure._id}')" class="text-red-600 hover:text-red-900 font-medium text-sm flex items-center">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        Delete
                    </button>
                </div>
            `;
            return card;
        }

        async function fetchEntries() {
            structuresList.innerHTML = ''; // Clear previous results
            noResultsMessage.classList.add('hidden');
            loadingSpinner.classList.remove('hidden');
            searchSpinner.classList.remove('hidden');
            searchButton.disabled = true;

            const nameQuery = nameSearchInput.value.trim();
            const peakType = document.querySelector('input[name="peakType"]:checked').value;
            const hShift = peakSearchInput1.value.trim();
            const cShift = peakSearchInput2.value.trim(); // Will be used for HSQC/HMBC C shift or COSY H2 shift

            let url = API_BASE_URL;
            const params = new URLSearchParams();

            if (nameQuery) {
                params.append('name', nameQuery);
            } else if (peakType && (hShift || cShift)) {
                params.append('peakType', peakType);
                if (hShift) params.append('hShift', hShift);
                if (cShift) params.append('cShift', cShift); // For COSY, this is h2Shift; for HSQC/HMBC, cShift
            }

            if (params.toString()) {
                url += `?${params.toString()}`;
            }

            try {
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const entries = await response.json();

                if (entries.length === 0) {
                    noResultsMessage.classList.remove('hidden');
                } else {
                    entries.forEach(structure => {
                        structuresList.appendChild(createStructureCard(structure));
                    });
                }
            } catch (error) {
                console.error("Error fetching structures:", error);
                showMessage(`Error fetching structures: ${error.message}`, true);
                noResultsMessage.textContent = "Error loading structures. Please try again.";
                noResultsMessage.classList.remove('hidden');
            } finally {
                loadingSpinner.classList.add('hidden');
                searchSpinner.classList.add('hidden');
                searchButton.disabled = false;
            }
        }

        function togglePeakInputs() {
            const selectedType = document.querySelector('input[name="peakType"]:checked').value;
            peakSearchInput1.value = '';
            peakSearchInput2.value = '';

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
        }

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

        // Event Listeners
        searchButton.addEventListener('click', fetchEntries);
        // Ensure functions are globally accessible if called from HTML onclick
        window.deleteStructure = deleteStructure;
        window.showImageModal = showImageModal;
        window.closeImageModal = closeImageModal;
        window.togglePeakInputs = togglePeakInputs; // Make it globally available

        // Message display function (copied from index.html for consistency)
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
    <title>NMR Structure Database - Compare NMR Peaks</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
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
        .plot-container {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            background-color: white;
            padding: 1rem;
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
                    <a href="/" class="nav-link">Add/Edit Structure</a>
                    <a href="/structures.html" class="nav-link">View Structures</a>
                    <a href="/analysis.html" class="nav-link active-nav-link">NMR Analysis</a>
                    <a href="/compare.html" class="nav-link">Compare NMR Peaks</a>
                </div>
            </div>
        </nav>

        <main class="flex-grow container mx-auto p-4 sm:p-6 lg:p-8">
            <h1 class="text-3xl font-bold text-gray-800 mb-6">NMR Mixture Analysis</h1>

            <div id="message" class="hidden bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mb-6" role="alert">
                <p id="message-text" class="font-bold"></p>
            </div>
            <div id="error-message" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-6" role="alert">
                <p id="error-message-text" class="font-bold"></p>
            </div>

            <div class="bg-white p-6 rounded-lg shadow-md mb-8">
                <h2 class="text-xl font-semibold text-gray-700 mb-4">Input NMR Data</h2>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                    <div>
                        <label for="hsqcData" class="block text-sm font-medium text-gray-700">HSQC Peaks (1H, 13C, optional Intensity)</label>
                        <textarea id="hsqcData" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16 1.0&#10;5.12 101.3 0.8&#10;..."></textarea>
                        <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift [Intensity] (one peak per line)</p>
                    </div>
                    <div>
                        <label for="cosyData" class="block text-sm font-medium text-gray-700">COSY Peaks (1H, 1H, optional Intensity)</label>
                        <textarea id="cosyData" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 7.26 1.0&#10;5.12 3.45 0.5&#10;..."></textarea>
                        <p class="text-xs text-gray-500 mt-1">Format: 1H_shift1 1H_shift2 [Intensity] (one peak per line)</p>
                    </div>
                    <div>
                        <label for="hmbcData" class="block text-sm font-medium text-gray-700">HMBC Peaks (1H, 13C, optional Intensity)</label>
                        <textarea id="hmbcData" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16 1.0&#10;5.12 101.3 0.8&#10;..."></textarea>
                        <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift [Intensity] (one peak per line)</p>
                    </div>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                    <div>
                        <label for="toleranceH" class="block text-sm font-medium text-gray-700">1H Tolerance (ppm)</label>
                        <input type="number" step="0.01" id="toleranceH" value="0.05"
                               class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                    <div>
                        <label for="toleranceC" class="block text-sm font-medium text-gray-700">13C Tolerance (ppm)</label>
                        <input type="number" step="0.01" id="toleranceC" value="0.50"
                               class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                </div>
                <button id="analyzeBtn"
                        class="bg-indigo-600 text-white font-bold py-2 px-4 rounded-md shadow-md hover:bg-indigo-700 transition duration-300 flex items-center justify-center">
                    <svg class="animate-spin h-5 w-5 text-white mr-3 hidden" viewBox="0 0 24 24" id="analyzeSpinner">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Analyze Sample</span>
                </button>
            </div>

            <div id="resultsSection" class="bg-white p-6 rounded-lg shadow-md hidden">
                <h2 class="text-xl font-semibold text-gray-700 mb-4">Analysis Results</h2>

                <div class="mb-6">
                    <h3 class="text-lg font-medium text-gray-800 mb-2">Detected Structures:</h3>
                    <ul id="detectedStructuresList" class="list-disc pl-5 text-gray-700">
                        </ul>
                    <p id="noDetectedStructuresMessage" class="text-gray-600 mt-2 hidden">No structures detected in the sample.</p>
                </div>

                <div class="mb-6">
                    <h3 class="text-lg font-medium text-gray-800 mb-2">Unmatched Sample Peaks:</h3>
                    <div id="unmatchedPeaksDisplay">
                        <p class="text-gray-600 mb-2" id="noUnmatchedPeaksMessage">No unmatched peaks remaining.</p>
                        <div id="unmatchedHsqc" class="mb-2 hidden">
                            <h4 class="font-medium text-gray-700">Unmatched HSQC Peaks:</h4>
                            <ul class="list-disc pl-5 text-sm text-gray-700"></ul>
                        </div>
                        <div id="unmatchedCosy" class="mb-2 hidden">
                            <h4 class="font-medium text-gray-700">Unmatched COSY Peaks:</h4>
                            <ul class="list-disc pl-5 text-sm text-gray-700"></ul>
                        </div>
                        <div id="unmatchedHmbc" class="mb-2 hidden">
                            <h4 class="font-medium text-gray-700">Unmatched HMBC Peaks:</h4>
                            <ul class="list-disc pl-5 text-sm text-gray-700"></ul>
                        </div>
                    </div>
                </div>

                <h3 class="text-lg font-medium text-gray-800 mb-4">NMR Plots:</h3>
                <div class="grid grid-cols-1 md:grid-cols-1 gap-6">
                    <div id="hsqcPlotContainer" class="plot-container h-96"></div>
                    <div id="cosyPlotContainer" class="plot-container h-96"></div>
                    <div id="hmbcPlotContainer" class="plot-container h-96"></div>
                </div>
            </div>
        </main>

        <footer class="bg-gray-800 text-white text-center p-4 mt-8">
            <p>&copy; 2023 NMR Structure Database. All rights reserved.</p>
        </footer>
    </div>

    <script>
        // DOM elements
        const hsqcDataInput = document.getElementById('hsqcData');
        const cosyDataInput = document.getElementById('cosyData');
        const hmbcDataInput = document.getElementById('hmbcData');
        const toleranceHInput = document.getElementById('toleranceH');
        const toleranceCInput = document.getElementById('toleranceC');
        const analyzeBtn = document.getElementById('analyzeBtn');
        const analyzeSpinner = document.getElementById('analyzeSpinner');
        const resultsSection = document.getElementById('resultsSection');
        const detectedStructuresList = document.getElementById('detectedStructuresList');
        const noDetectedStructuresMessage = document.getElementById('noDetectedStructuresMessage');
        const unmatchedPeaksDisplay = document.getElementById('unmatchedPeaksDisplay');
        const noUnmatchedPeaksMessage = document.getElementById('noUnmatchedPeaksMessage');
        const unmatchedHsqcList = document.querySelector('#unmatchedHsqc ul');
        const unmatchedCosyList = document.querySelector('#unmatchedCosy ul');
        const unmatchedHmbcList = document.querySelector('#unmatchedHmbc ul');
        const unmatchedHsqcDiv = document.getElementById('unmatchedHsqc');
        const unmatchedCosyDiv = document.getElementById('unmatchedCosy');
        const unmatchedHmbcDiv = document.getElementById('unmatchedHmbc');
        const hsqcPlotContainer = document.getElementById('hsqcPlotContainer');
        const cosyPlotContainer = document.getElementById('cosyPlotContainer');
        const hmbcPlotContainer = document.getElementById('hmbcPlotContainer');

        analyzeBtn.addEventListener('click', analyzeSample);

        async function analyzeSample() {
            // Clear previous results and messages
            detectedStructuresList.innerHTML = '';
            unmatchedHsqcList.innerHTML = '';
            unmatchedCosyList.innerHTML = '';
            unmatchedHmbcList.innerHTML = '';
            resultsSection.classList.add('hidden');
            noDetectedStructuresMessage.classList.add('hidden');
            noUnmatchedPeaksMessage.classList.add('hidden');
            unmatchedHsqcDiv.classList.add('hidden');
            unmatchedCosyDiv.classList.add('hidden');
            unmatchedHmbcDiv.classList.add('hidden');
            
            // Clear previous plots
            Plotly.purge(hsqcPlotContainer);
            Plotly.purge(cosyPlotContainer);
            Plotly.purge(hmbcPlotContainer);

            // Show loading state
            analyzeBtn.disabled = true;
            analyzeSpinner.classList.remove('hidden');

            const hsqc_data = hsqcDataInput.value;
            const cosy_data = cosyDataInput.value;
            const hmbc_data = hmbcDataInput.value;
            const tolerance_h = parseFloat(toleranceHInput.value);
            const tolerance_c = parseFloat(toleranceCInput.value);

            if (!hsqc_data.trim() && !cosy_data.trim() && !hmbc_data.trim()) {
                showMessage('Please enter at least one type of NMR data for analysis.', true);
                analyzeBtn.disabled = false;
                analyzeSpinner.classList.add('hidden');
                return;
            }

            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        hsqc_data: hsqc_data,
                        cosy_data: cosy_data,
                        hmbc_data: hmbc_data,
                        tolerance_h: tolerance_h,
                        tolerance_c: tolerance_c
                    })
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Analysis failed');
                }

                if (result.success) {
                    displayAnalysisResults(result);
                    resultsSection.classList.remove('hidden');
                } else {
                    showMessage(result.error || 'Analysis failed.', true);
                }
            } catch (error) {
                console.error("Error during NMR analysis:", error);
                showMessage(`Error: ${error.message}`, true);
            } finally {
                analyzeBtn.disabled = false;
                analyzeSpinner.classList.add('hidden');
            }
        }

        function displayAnalysisResults(data) {
            // Display Detected Structures
            if (data.detected_entries && data.detected_entries.length > 0) {
                data.detected_entries.forEach(entry => {
                    const li = document.createElement('li');
                    li.textContent = `${entry.name} (Matched HSQC: ${entry.matched_hsqc_peaks}/${entry.total_hsqc_peaks}, Matched COSY: ${entry.matched_cosy_peaks}/${entry.total_cosy_peaks}, Matched HMBC: ${entry.matched_hmbc_peaks}/${entry.total_hmbc_peaks})`;
                    detectedStructuresList.appendChild(li);
                });
            } else {
                noDetectedStructuresMessage.classList.remove('hidden');
            }

            // Display Unmatched Sample Peaks
            const unmatchedPeaks = data.unmatched_sample_peaks;
            let hasUnmatched = false;

            if (unmatchedPeaks.hsqc && unmatchedPeaks.hsqc.length > 0) {
                unmatchedPeaks.hsqc.forEach(peak => {
                    const li = document.createElement('li');
                    li.textContent = `1H: ${peak[0]}, 13C: ${peak[1]}`;
                    unmatchedHsqcList.appendChild(li);
                });
                unmatchedHsqcDiv.classList.remove('hidden');
                hasUnmatched = true;
            }
            if (unmatchedPeaks.cosy && unmatchedPeaks.cosy.length > 0) {
                unmatchedPeaks.cosy.forEach(peak => {
                    const li = document.createElement('li');
                    li.textContent = `1H1: ${peak[0]}, 1H2: ${peak[1]}`;
                    unmatchedCosyList.appendChild(li);
                });
                unmatchedCosyDiv.classList.remove('hidden');
                hasUnmatched = true;
            }
            if (unmatchedPeaks.hmbc && unmatchedPeaks.hmbc.length > 0) {
                unmatchedPeaks.hmbc.forEach(peak => {
                    const li = document.createElement('li');
                    li.textContent = `1H: ${peak[0]}, 13C: ${peak[1]}`;
                    unmatchedHmbcList.appendChild(li);
                });
                unmatchedHmbcDiv.classList.remove('hidden');
                hasUnmatched = true;
            }

            if (!hasUnmatched) {
                noUnmatchedPeaksMessage.classList.remove('hidden');
            }

            // Display Plots (if available)
            if (data.hsqc_image_base64) {
                const img = document.createElement('img');
                img.src = `data:image/png;base64,${data.hsqc_image_base64}`;
                img.alt = 'HSQC Plot';
                img.className = 'max-w-full h-auto';
                hsqcPlotContainer.innerHTML = ''; // Clear existing content
                hsqcPlotContainer.appendChild(img);
            } else {
                hsqcPlotContainer.innerHTML = '<p class="text-gray-500 text-center">No HSQC plot generated.</p>';
            }

            if (data.cosy_image_base64) {
                const img = document.createElement('img');
                img.src = `data:image/png;base64,${data.cosy_image_base64}`;
                img.alt = 'COSY Plot';
                img.className = 'max-w-full h-auto';
                cosyPlotContainer.innerHTML = ''; // Clear existing content
                cosyPlotContainer.appendChild(img);
            } else {
                cosyPlotContainer.innerHTML = '<p class="text-gray-500 text-center">No COSY plot generated.</p>';
            }

            if (data.hmbc_image_base64) {
                const img = document.createElement('img');
                img.src = `data:image/png;base64,${data.hmbc_image_base64}`;
                img.alt = 'HMBC Plot';
                img.className = 'max-w-full h-auto';
                hmbcPlotContainer.innerHTML = ''; // Clear existing content
                hmbcPlotContainer.appendChild(img);
            } else {
                hmbcPlotContainer.innerHTML = '<p class="text-gray-500 text-center">No HMBC plot generated.</p>';
            }
        }

        // Show message function (copied from index.html for consistency)
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
            <h1 class="text-3xl font-bold text-gray-800 mb-6">Quick Compare HSQC Peaks to Database</h1>

            <div id="message" class="hidden bg-green-100 border-l-4 border-green-500 text-green-700 p-4 mb-6" role="alert">
                <p id="message-text" class="font-bold"></p>
            </div>
            <div id="error-message" class="hidden bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-6" role="alert">
                <p id="error-message-text" class="font-bold"></p>
            </div>

            <div class="bg-white p-6 rounded-lg shadow-md mb-8">
                <h2 class="text-xl font-semibold text-gray-700 mb-4">Input HSQC Peaks</h2>
                <div class="mb-4">
                    <label for="hsqcPeaksInput" class="block text-sm font-medium text-gray-700">HSQC Peaks (1H, 13C, optional Intensity)</label>
                    <textarea id="hsqcPeaksInput" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="3.35 49.7 1.0&#10;7.20 128.1 0.5&#10;..."></textarea>
                    <p class="text-xs text-gray-500 mt-1">Format: 1H_shift 13C_shift [Intensity] (one peak per line)</p>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                    <div>
                        <label for="delta1H" class="block text-sm font-medium text-gray-700">1H Tolerance (ppm)</label>
                        <input type="number" step="0.01" id="delta1H" value="0.06"
                               class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                    <div>
                        <label for="delta13C" class="block text-sm font-medium text-gray-700">13C Tolerance (ppm)</label>
                        <input type="number" step="0.01" id="delta13C" value="0.8"
                               class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50">
                    </div>
                </div>
                <button id="compareBtn"
                        class="bg-indigo-600 text-white font-bold py-2 px-4 rounded-md shadow-md hover:bg-indigo-700 transition duration-300 flex items-center justify-center">
                    <svg class="animate-spin h-5 w-5 text-white mr-3 hidden" viewBox="0 0 24 24" id="compareSpinner">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Compare Peaks</span>
                </button>
            </div>

            <div id="comparisonResultsDiv" class="bg-white p-6 rounded-lg shadow-md hidden">
                <h2 class="text-xl font-semibold text-gray-700 mb-4">Comparison Results</h2>

                <div class="mb-4">
                    <h3 class="text-lg font-medium text-gray-800 mb-2">Fully Matched Compounds:</h3>
                    <ul id="fullyMatchedList" class="list-disc pl-5 text-gray-700">
                        </ul>
                    <p id="noFullyMatched" class="text-gray-600 mt-2 hidden">No compounds fully matched.</p>
                </div>

                <div>
                    <h3 class="text-lg font-medium text-gray-800 mb-2">Partially Matched Compounds:</h3>
                    <ul id="partiallyMatchedList" class="list-disc pl-5 text-gray-700">
                        </ul>
                    <p id="noPartiallyMatched" class="text-gray-600 mt-2 hidden">No compounds partially matched.</p>
                </div>
            </div>
        </main>

        <footer class="bg-gray-800 text-white text-center p-4 mt-8">
            <p>&copy; 2023 NMR Structure Database. All rights reserved.</p>
        </footer>
    </div>

    <script>
        const hsqcPeaksInput = document.getElementById('hsqcPeaksInput');
        const delta1HInput = document.getElementById('delta1H');
        const delta13CInput = document.getElementById('delta13C');
        const compareBtn = document.getElementById('compareBtn');
        const compareSpinner = document.getElementById('compareSpinner');
        const comparisonResultsDiv = document.getElementById('comparisonResultsDiv');
        const fullyMatchedList = document.getElementById('fullyMatchedList');
        const partiallyMatchedList = document.getElementById('partiallyMatchedList');
        const noFullyMatched = document.getElementById('noFullyMatched');
        const noPartiallyMatched = document.getElementById('noPartiallyMatched');

        compareBtn.addEventListener('click', comparePeaks);

        async function comparePeaks() {
            // Clear previous results
            fullyMatchedList.innerHTML = '';
            partiallyMatchedList.innerHTML = '';
            noFullyMatched.classList.add('hidden');
            noPartiallyMatched.classList.add('hidden');
            comparisonResultsDiv.classList.add('hidden');

            // Show loading state
            compareBtn.disabled = true;
            compareSpinner.classList.remove('hidden');

            const hsqcPeaks = hsqcPeaksInput.value;
            const delta1H = parseFloat(delta1HInput.value);
            const delta13C = parseFloat(delta13CInput.value);

            if (!hsqcPeaks.trim()) {
                showMessage('Please enter HSQC peaks for comparison.', true);
                compareBtn.disabled = false;
                compareSpinner.classList.add('hidden');
                return;
            }

            try {
                const response = await fetch('/api/quick-match', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        hsqcPeaks: hsqcPeaks,
                        d1h: delta1H,
                        d13c: delta13C
                    })
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Comparison failed');
                }

                displayComparisonResults(result);
            } catch (error) {
                console.error("Error during peak comparison:", error);
                showMessage(`Error: ${error.message}`, true);
            } finally {
                compareBtn.disabled = false;
                compareSpinner.classList.add('hidden');
            }
        }

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

        // Show message function
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