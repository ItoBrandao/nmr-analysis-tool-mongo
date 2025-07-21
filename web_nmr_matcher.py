from flask import Flask, request, render_template_string, jsonify
import pandas as pd
import json

app = Flask(__name__)

# Define the route for the analysis page
@app.route('/analysis.html')
def analysis():
    return render_template_string(ANALYSIS_PAGE)

# Define the route for the compare page
@app.route('/compare.html')
def compare():
    return render_template_string(COMPARE_PAGE)

# Define the API endpoint for comparing NMR peaks
@app.route('/api/compare', methods=['POST'])
def api_compare():
    data = request.get_json()
    hsqc_peaks = data.get('hsqcPeaks', '')
    cosy_peaks = data.get('cosyPeaks', '')
    hmbc_peaks = data.get('hmbcPeaks', '')

    # Call your comparison function here
    comparison_results = compare_peaks(hsqc_peaks, cosy_peaks, hmbc_peaks)

    return jsonify(comparison_results)

# Example comparison function (you will need to implement the actual logic)
def compare_peaks(hsqc_peaks, cosy_peaks, hmbc_peaks):
    # Placeholder for actual comparison logic
    return {
        "hsqc": "Comparison result for HSQC",
        "cosy": "Comparison result for COSY",
        "hmbc": "Comparison result for HMBC"
    }

# Define the HTML content for the analysis page
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
            <!-- Your analysis content here -->
        </main>

        <footer class="bg-gray-800 text-white text-center p-4">
            <p>&copy; 2023 NMR Structure Database. All rights reserved.</p>
        </footer>
    </div>
</body>
</html>
"""

# Define the HTML content for the compare page
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
            <h1 class="text-3xl font-bold text-gray-800 mb-6">Compare NMR Peaks</h1>

            <div class="bg-white p-6 rounded-lg shadow-md mb-8">
                <form id="compareForm" class="space-y-6">
                    <div>
                        <label for="hsqcPeaks" class="block text-sm font-medium text-gray-700">HSQC Peaks (1H, 13C)</label>
                        <textarea id="hsqcPeaks" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16&#10;5.12 101.3&#10;..."></textarea>
                    </div>
                    <div>
                        <label for="cosyPeaks" class="block text-sm font-medium text-gray-700">COSY Peaks (1H, 1H)</label>
                        <textarea id="cosyPeaks" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 7.26&#10;5.12 3.45&#10;..."></textarea>
                    </div>
                    <div>
                        <label for="hmbcPeaks" class="block text-sm font-medium text-gray-700">HMBC Peaks (1H, 13C)</label>
                        <textarea id="hmbcPeaks" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-300 focus:ring focus:ring-indigo-200 focus:ring-opacity-50" placeholder="7.26 77.16&#10;5.12 101.3&#10;..."></textarea>
                    </div>
                    <div class="flex justify-end space-x-2">
                        <button type="submit" class="bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 flex items-center">
                            Compare Peaks
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
        const API_BASE_URL = '/api/compare';

        document.getElementById('compareForm').addEventListener('submit', async (e) => {
            e.preventDefault();

            const hsqcPeaks = document.getElementById('hsqcPeaks').value.trim();
            const cosyPeaks = document.getElementById('cosyPeaks').value.trim();
            const hmbcPeaks = document.getElementById('hmbcPeaks').value.trim();

            if (!hsqcPeaks && !cosyPeaks && !hmbcPeaks) {
                // Using a custom message box instead of alert()
                showMessage('Please enter at least one set of peaks.', true);
                return;
            }

            try {
                const response = await fetch(API_BASE_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ hsqcPeaks, cosyPeaks, hmbcPeaks })
                });

                if (!response.ok) {
                    throw new Error('Failed to compare peaks.');
                }

                const result = await response.json();
                // Using a custom message box instead of alert()
                showMessage('Comparison results: ' + JSON.stringify(result));
            } catch (error) {
                // Using a custom message box instead of alert()
                showMessage('Error comparing peaks: ' + error.message, true);
            }
        });

        // Custom message function (replace alert)
        function showMessage(message, isError = false) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `fixed top-4 right-4 p-4 rounded-md shadow-lg text-white ${isError ? 'bg-red-500' : 'bg-green-500'}`;
            messageDiv.textContent = message;
            document.body.appendChild(messageDiv);

            setTimeout(() => {
                messageDiv.remove();
            }, 5000); // Hide after 5 seconds
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True)