import pandas as pd
import matplotlib
matplotlib.use('Agg') # This line sets the non-interactive backend
import matplotlib.pyplot as plt
import io
import base64
import re
import numpy as np
from scipy.ndimage import gaussian_filter
import matplotlib.cm as cm
from scipy.stats import multivariate_normal
import logging
import copy # Import the copy module
from flask import jsonify, request  # Added for API endpoint

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- CHANGE START: These are now the DEFAULT tolerances ---
TOLERANCE_H_MATCH = 0.05
TOLERANCE_C_MATCH = 0.50
# --- CHANGE END ---

GRID_RESOLUTION = 800
CONTOUR_LINE_WIDTH = 1.0

plt.rcParams['font.family'] = 'Arial'
plt.rcParams['axes.labelcolor'] = 'black'
plt.rcParams['xtick.color'] = 'black'
plt.rcParams['ytick.color'] = 'black'
plt.rcParams['axes.edgecolor'] = 'black'
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.facecolor'] = 'white'
plt.rcParams['grid.color'] = 'lightgray'
plt.rcParams['grid.linestyle'] = '-'
plt.rcParams['grid.alpha'] = 0.5
plt.rcParams['contour.linewidth'] = CONTOUR_LINE_WIDTH
plt.rcParams['axes.linewidth'] = 1.0
plt.rcParams['xtick.major.width'] = 1.0
plt.rcParams['ytick.major.size'] = 5
plt.rcParams['ytick.major.size'] = 5
plt.rcParams['axes.titlesize'] = 16
plt.rcParams['axes.titleweight'] = 'bold'
plt.rcParams['axes.labelsize'] = 14

def _parse_single_value_or_range(val_str):
    if not isinstance(val_str, str):
        logger.warning(f"Expected string for _parse_single_value_or_range, got {type(val_str)}. Returning None.")
        return None
    val_str = val_str.strip()
    if '-' in val_str:
        try:
            start, end = map(float, val_str.split('-'))
            return (start + end) / 2
        except ValueError:
            logger.error(f"Invalid range format: '{val_str}'. Expected 'X.X-Y.Y'.")
            return None
    else:
        try:
            return float(val_str)
        except ValueError:
            logger.error(f"Invalid single value format: '{val_str}'. Expected 'X.X'.")
            return None

def parse_peak_data(peak_data, nmr_type):
    peaks = []
    logger.debug(f"Attempting to parse peak data for type: {nmr_type}, data type: {type(peak_data)}")

    if nmr_type == 'cosy':
        logger.debug(f"COSY - Raw peak_data input type: {type(peak_data)}")
        if isinstance(peak_data, str):
            logger.debug(f"COSY - Raw string length: {len(peak_data) if peak_data is not None else 'None'}")
            if peak_data is not None:
                escaped_peak_data = peak_data.encode('unicode_escape').decode('utf-8')
                logger.debug(f"COSY - Raw string (first 100 chars, escaped): '{escaped_peak_data[:100]}'")
                logger.debug(f"COSY - Stripped string length: {len(peak_data.strip())}")
                stripped_escaped_peak_data = peak_data.strip().encode('unicode_escape').decode('utf-8')
                logger.debug(f"COSY - Stripped string (first 100 chars, escaped): '{stripped_escaped_peak_data[:100]}'")
                logger.debug(f"COSY - Is stripped string empty? {peak_data.strip() == ''}")
        elif isinstance(peak_data, list):
            logger.debug(f"COSY - Raw list input: {peak_data[:5]} (first 5 elements)")
        else:
            logger.debug(f"COSY - Raw peak_data is neither string nor list. Type: {type(peak_data)}")

    if not peak_data:
        logger.debug(f"Empty peak data provided for {nmr_type}. Returning empty DataFrame.")
        if nmr_type in ['hsqc', 'hmbc']:
            return pd.DataFrame(columns=['H', 'C', 'Intensity'])
        elif nmr_type == 'cosy':
            return pd.DataFrame(columns=['H1', 'H2', 'Intensity'])
        return pd.DataFrame()

    if isinstance(peak_data, str):
        lines = peak_data.strip().split('\n')
        # Skip header line if present (e.g., "1H 13C Intensity")
        if lines and re.match(r'^\s*(?:1H|H1)\s+(?:13C|H2)\s+Intensity\s*$', lines[0].strip(), re.IGNORECASE):
            logger.debug(f"Skipping header line: '{lines[0].strip()}' for {nmr_type}.")
            lines = lines[1:]

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # This regex is robust for space or tab delimited values.
            # It expects two shift values (which can be ranges) followed by an optional intensity.
            match = re.match(r'^\s*([\d\.]+(?:-[\d\.]+)?)\s+([\d\.]+(?:-[\d\.]+)?)\s*(\d*\.?\d*)?\s*$', line)
            
            if match:
                shift1_str = match.group(1)
                shift2_str = match.group(2)
                intensity_str = match.group(3)
                
                shift1 = _parse_single_value_or_range(shift1_str)
                shift2 = _parse_single_value_or_range(shift2_str)
                intensity = float(intensity_str) if intensity_str else 1.0

                if shift1 is None or shift2 is None:
                    logger.warning(f"Warning: Could not parse shifts in line (string input): '{line}'. Skipping.")
                    continue

                if nmr_type in ['hsqc', 'hmbc']:
                    peaks.append({'H': shift1, 'C': shift2, 'Intensity': intensity})
                elif nmr_type == 'cosy':
                    peaks.append({'H1': shift1, 'H2': shift2, 'Intensity': intensity})
            else:
                logger.warning(f"Warning: Line did not match expected format for {nmr_type} (string input): '{line}'. Skipping.")

    elif isinstance(peak_data, list):
        for peak_dict in peak_data:
            if not isinstance(peak_dict, dict):
                logger.warning(f"Expected dictionary in peak_data list, got {type(peak_dict)}. Skipping.")
                continue

            try:
                if nmr_type in ['hsqc', 'hmbc']:
                    shift1_str = peak_dict.get('H')
                    shift2_str = peak_dict.get('C')
                    col1_name, col2_name = 'H', 'C'
                elif nmr_type == 'cosy':
                    shift1_str = peak_dict.get('H1')
                    shift2_str = peak_dict.get('H2')
                    col1_name, col2_name = 'H1', 'H2'
                else:
                    logger.error(f"Unknown nmr_type: {nmr_type} in structured peak data. Skipping peak_dict: {peak_dict}")
                    continue

                shift1 = _parse_single_value_or_range(shift1_str)
                shift2 = _parse_single_value_or_range(shift2_str)
                intensity = float(peak_dict.get('Intensity', 1.0))

                if shift1 is None or shift2 is None:
                    logger.warning(f"Warning: Could not parse shifts from structured peak: {peak_dict}. Skipping.")
                    continue

                peak_entry = {col1_name: shift1, col2_name: shift2, 'Intensity': intensity}
                peaks.append(peak_entry)

            except Exception as e:
                logger.error(f"Error processing structured peak: {peak_dict}. Error: {e}. Skipping.")

    else:
        logger.error(f"Unsupported peak data type: {type(peak_data)}. Expected str or list. Returning empty DataFrame.")
        if nmr_type in ['hsqc', 'hmbc']:
            return pd.DataFrame(columns=['H', 'C', 'Intensity'])
        elif nmr_type == 'cosy':
            return pd.DataFrame(columns=['H1', 'H2', 'Intensity'])
        return pd.DataFrame()
        
    if nmr_type in ['hsqc', 'hmbc']:
        df = pd.DataFrame(peaks, columns=['H', 'C', 'Intensity'])
    elif nmr_type == 'cosy':
        df = pd.DataFrame(peaks, columns=['H1', 'H2', 'Intensity'])
    else:
        logger.error(f"Unknown nmr_type: {nmr_type} in parse_peak_data after parsing. Returning empty DataFrame.")
        df = pd.DataFrame()

    logger.debug(f"Parsed peaks DataFrame for {nmr_type}:\n{df.to_string() if not df.empty else 'Empty DataFrame'}")
    return df


def generate_nmr_plots(hsqc_data, cosy_data, hmbc_data, num_contour_levels=15):
    plots_base64 = []

    plot_types = {
        'hsqc': {'title': 'HSQC Spectrum', 'xlabel': '¹H (ppm)', 'ylabel': '¹³C (ppm)', 'x_col': 'H', 'y_col': 'C', 'y_invert': True, 'x_padding_ratio': 0.05, 'y_padding_value': 10},
        'cosy': {'title': 'COSY Spectrum', 'xlabel': '¹H (ppm)', 'ylabel': '¹H (ppm)', 'x_col': 'H1', 'y_col': 'H2', 'y_invert': True, 'x_padding_ratio': 0.05, 'y_padding_value': 0.5},
        'hmbc': {'title': 'HMBC Spectrum', 'xlabel': '¹H (ppm)', 'ylabel': '¹³C (ppm)', 'x_col': 'H', 'y_col': 'C', 'y_invert': True, 'x_padding_ratio': 0.05, 'y_padding_value': 10}
    }

    raw_data_inputs = {
        'hsqc': hsqc_data,
        'cosy': cosy_data,
        'hmbc': hmbc_data
    }

    num_contour_levels = max(1, min(50, num_contour_levels))

    for peak_type, config in plot_types.items():
        fig, ax = plt.subplots(figsize=(8, 8))
        
        try:
            parsed_peaks = parse_peak_data(raw_data_inputs[peak_type], peak_type)
            
            ax.grid(True)

            if parsed_peaks.empty:
                logger.info(f"No data for {peak_type} plot. Generating empty plot.")
                ax.set_title(f"{config['title']} (No peaks provided)")
                ax.set_xlabel(config['xlabel'])
                ax.set_ylabel(config['ylabel'])
                
                ax.set_xlim(0, 10)
                if config['y_col'] == 'C':
                    ax.set_ylim(0, 200)
                else:
                    ax.set_ylim(0, 10)

                ax.invert_xaxis()
                if config['y_invert']:
                    ax.invert_yaxis()

                img_buffer = io.BytesIO()
                plt.savefig(img_buffer, format='png', bbox_inches='tight', dpi=150)
                img_buffer.seek(0)
                plots_base64.append(base64.b64encode(img_buffer.getvalue()).decode('utf-8'))
                plt.close(fig)
                continue

            if peak_type == 'cosy':
                if 'H1' in parsed_peaks.columns and 'H2' in parsed_peaks.columns:
                    # Add symmetric peaks for plotting COSY
                    parsed_peaks = pd.concat([parsed_peaks, parsed_peaks.rename(columns={'H1': 'H2', 'H2': 'H1'})], ignore_index=True)
                    logger.debug(f"COSY - Parsed peaks (after adding symmetric for plot):\n{parsed_peaks.to_string()}")


            x_data = parsed_peaks[config['x_col']].values
            y_data = parsed_peaks[config['y_col']].values
            intensity_data = parsed_peaks['Intensity'].values

            x_min, x_max = x_data.min(), x_data.max()
            y_min, y_max = y_data.min(), y_data.max()

            x_range_data = x_max - x_min
            y_range_data = y_max - y_min

            x_padding = max(x_range_data * config['x_padding_ratio'], 0.5)
            y_padding = max(y_range_data * config['x_padding_ratio'], config['y_padding_value'])

            current_xlim = (x_min - x_padding, x_max + x_padding)
            current_ylim = (y_min - y_padding, y_max + y_padding)

            ax.set_xlim(current_xlim)
            ax.set_ylim(current_ylim)
            
            ax.invert_xaxis()
            if config['y_invert']:
                ax.invert_yaxis()

            num_grid_points = 250
            xi = np.linspace(ax.get_xlim()[0], ax.get_xlim()[1], num_grid_points)
            yi = np.linspace(ax.get_ylim()[0], ax.get_ylim()[1], num_grid_points)
            X, Y = np.meshgrid(xi, yi)
            Z = np.zeros(X.shape)

            if peak_type == 'cosy':
                sigma_x = max((abs(ax.get_xlim()[1] - ax.get_xlim()[0])) / 1500, 0.0025)
                sigma_y = sigma_x
            else:
                sigma_x = max((abs(ax.get_xlim()[1] - ax.get_xlim()[0])) / 1800, 0.0015)
                sigma_y = max((abs(ax.get_ylim()[1] - ax.get_ylim()[0])) / 1800, 0.015)

            for i in range(len(x_data)):
                mean = [x_data[i], y_data[i]]
                covariance = [[sigma_x**2, 0], [0, sigma_y**2]]
                rv = multivariate_normal(mean, covariance)
                Z += intensity_data[i] * rv.pdf(np.dstack([X, Y]))

            Z = gaussian_filter(Z, sigma=(1.0, 1.0))

            if peak_type == 'cosy':
                epsilon = 1e-9 # Small epsilon to prevent log(0)
                Z_transformed = np.log10(Z + epsilon)
                
                if Z_transformed.max() > Z_transformed.min():
                    Z_normalized = (Z_transformed - Z_transformed.min()) / (Z_transformed.max() - Z_transformed.min())
                else:
                    Z_normalized = np.zeros_like(Z_transformed)
            else:
                if Z.max() > 0:
                    Z_normalized = Z / Z.max()
                else:
                    Z_normalized = Z

            if Z_normalized.max() > 0:
                if peak_type == 'cosy':
                    min_contour_val = 0.05
                    max_contour_val = 1.0
                    contour_levels = np.linspace(min_contour_val, max_contour_val, num_contour_levels)
                else:
                    current_max_val = Z_normalized.max()
                    if current_max_val <= 0:
                        logger.warning(f"Z_normalized.max() is non-positive for {peak_type}. Skipping contour generation.")
                        contour_levels = []
                    else:
                        min_val_for_log = max(0.001, 0.01 * current_max_val)
                        min_log_level = np.log10(min_val_for_log)
                        max_log_level = np.log10(current_max_val)
                        
                        if max_log_level <= min_log_level:
                            logger.warning(f"Log contour range invalid for {peak_type}. Falling back to linear levels.")
                            contour_levels = np.linspace(0.01 * current_max_val, current_max_val, num_contour_levels)
                        else:
                            contour_levels = np.logspace(min_log_level, max_log_level, num_contour_levels)
                
                contour_levels = [level for level in contour_levels if level > 0 and level <= 1.0]
                
                if contour_levels:
                    ax.contour(X, Y, Z_normalized, levels=contour_levels, colors='blue', linewidths=CONTOUR_LINE_WIDTH)
                else:
                    logger.info(f"No valid contour levels generated for {peak_type}.")
            else:
                logger.info(f"Z_normalized.max() is 0 or less for {peak_type}. Skipping contour generation.")
            
            if peak_type == 'cosy':
                diag_min = min(ax.get_xlim()[0], ax.get_ylim()[0])
                diag_max = max(ax.get_xlim()[1], ax.get_ylim()[1])
                ax.plot([diag_min, diag_max], [diag_min, diag_max], color='gray', linestyle='--', linewidth=1, label='Diagonal')
                ax.set_aspect('equal', adjustable='box')

            ax.set_title(config['title'])
            ax.set_xlabel(config['xlabel'])
            ax.set_ylabel(config['ylabel'])
            
            ax.minorticks_on()
            ax.tick_params(which='both', direction='in', top=True, right=True)

            plt.tight_layout()
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', bbox_inches='tight', dpi=150)
            img_buffer.seek(0)
            plots_base64.append(base64.b64encode(img_buffer.getvalue()).decode('utf-8'))

        except Exception as e:
            logger.error(f"Error generating {peak_type} plot: {str(e)}")
            plots_base64.append(None)
        finally:
            plt.close(fig)
    
    return (plots_base64[0] if len(plots_base64) > 0 else None,
            plots_base64[1] if len(plots_base64) > 1 else None,
            plots_base64[2] if len(plots_base64) > 2 else None)


def find_compound_matches(sample_peaks, db_peaks, tolerance_h, tolerance_c):
    """Find which database peaks match sample peaks."""
    matches = []
    # Create a set to keep track of matched sample peak indices to ensure each sample peak is used once.
    matched_sample_peak_indices = set() 

    # Convert db_peaks to a list of dicts if it's a DataFrame
    if isinstance(db_peaks, pd.DataFrame):
        db_peaks = db_peaks.to_dict('records')
    
    # Convert sample_peaks to a list of dicts if it's a DataFrame
    if isinstance(sample_peaks, pd.DataFrame):
        sample_peaks_list = sample_peaks.to_dict('records')
    else: # Assume it's already a list of dicts
        sample_peaks_list = sample_peaks

    for db_peak in db_peaks:
        for i, sample_peak in enumerate(sample_peaks_list):
            # Only consider sample peaks that haven't been matched yet
            if i not in matched_sample_peak_indices: 
                # Determine peak keys based on NMR type (H/C for HSQC/HMBC, H1/H2 for COSY)
                sample_h_key = 'H' if 'H' in sample_peak else 'H1'
                sample_c_key = 'C' if 'C' in sample_peak else 'H2'
                db_h_key = 'H' if 'H' in db_peak else 'H1'
                db_c_key = 'C' if 'C' in db_peak else 'H2'

                # Perform the match check
                if (abs(db_peak[db_h_key] - sample_peak[sample_h_key]) <= tolerance_h and 
                    abs(db_peak[db_c_key] - sample_peak[sample_c_key]) <= tolerance_c):
                    matches.append({
                        'sample_peak': sample_peak,
                        'db_peak': db_peak
                    })
                    # Mark this sample peak as matched
                    matched_sample_peak_indices.add(i) 
                    break  # Each sample peak can only match one db peak
    return matches


# --- CHANGE START: Update function to accept tolerance arguments ---
def analyze_mixture(sample_hsqc, sample_cosy, sample_hmbc, db_entries, 
                    tolerance_h=TOLERANCE_H_MATCH, tolerance_c=TOLERANCE_C_MATCH):
# --- CHANGE END ---
    """
    Analyzes a mixture of NMR data against a database of compounds to find matches.
    """
    logger.debug("--- Starting analyze_mixture (new algorithm) ---")
    results = []
    
    # Convert all sample peaks to unified format (list of dictionaries)
    # Using parse_peak_data to ensure consistency
    all_sample_peaks = {
        'hsqc': parse_peak_data(sample_hsqc, 'hsqc').to_dict('records'),
        'cosy': parse_peak_data(sample_cosy, 'cosy').to_dict('records'),
        'hmbc': parse_peak_data(sample_hmbc, 'hmbc').to_dict('records')
    }
    
    # Keep track of sample peaks that have been matched by *any* compound
    overall_matched_hsqc_indices = set()
    overall_matched_cosy_indices = set()
    overall_matched_hmbc_indices = set()

    for compound in db_entries:
        compound_name = compound.get('name', 'Unknown Compound')
        logger.debug(f"\n--- Checking database entry: {compound_name} (ID: {compound.get('id')}) ---")

        # Get all peaks for this compound from the database entry
        compound_peaks = {
            'hsqc': parse_peak_data(compound.get('hsqc_peaks', ''), 'hsqc').to_dict('records'),
            'cosy': parse_peak_data(compound.get('cosy_peaks', ''), 'cosy').to_dict('records'),
            'hmbc': parse_peak_data(compound.get('hmbc_peaks', ''), 'hmbc').to_dict('records')
        }
        
        # --- CHANGE START: Use the passed tolerance arguments for matching ---
        compound_hsqc_matches = find_compound_matches(all_sample_peaks['hsqc'], compound_peaks['hsqc'],
                                                    tolerance_h, tolerance_c)
        # Note: COSY uses H-H matching, so we use tolerance_h for both dimensions
        compound_cosy_matches = find_compound_matches(all_sample_peaks['cosy'], compound_peaks['cosy'],
                                                    tolerance_h, tolerance_h)
        compound_hmbc_matches = find_compound_matches(all_sample_peaks['hmbc'], compound_peaks['hmbc'],
                                                    tolerance_h, tolerance_c)
        # --- CHANGE END ---

        # Collect matched sample peak indices for overall unmatched calculation
        # This part requires a slight modification to correctly get the index of the matched sample peak
        # because the 'sample_peak' in 'compound_hsqc_matches' is a dictionary, not the original object in the list.
        # We need to find its original index.
        for match in compound_hsqc_matches:
            try:
                # Find the index of the matched sample_peak dictionary within the all_sample_peaks list
                idx = next(i for i, item in enumerate(all_sample_peaks['hsqc']) if item == match['sample_peak'])
                overall_matched_hsqc_indices.add(idx)
            except StopIteration:
                logger.warning(f"Matched HSQC sample peak {match['sample_peak']} not found in original list. This should not happen if logic is correct.")
        for match in compound_cosy_matches:
            try:
                idx = next(i for i, item in enumerate(all_sample_peaks['cosy']) if item == match['sample_peak'])
                overall_matched_cosy_indices.add(idx)
            except StopIteration:
                logger.warning(f"Matched COSY sample peak {match['sample_peak']} not found in original list. This should not happen if logic is correct.")
        for match in compound_hmbc_matches:
            try:
                idx = next(i for i, item in enumerate(all_sample_peaks['hmbc']) if item == match['sample_peak'])
                overall_matched_hmbc_indices.add(idx)
            except StopIteration:
                logger.warning(f"Matched HMBC sample peak {match['sample_peak']} not found in original list. This should not happen if logic is correct.")


        matches = {
            'hsqc': compound_hsqc_matches,
            'cosy': compound_cosy_matches,
            'hmbc': compound_hmbc_matches
        }
        
        # Calculate match scores (percentage of compound peaks found in sample)
        # For individual compound match percentages, we still use the count of *this compound's* peaks
        # that were found in the sample, regardless of whether another compound also matched that sample peak.
        hsqc_match_percentage = len(matches['hsqc']) / len(compound_peaks['hsqc']) if len(compound_peaks['hsqc']) > 0 else None
        cosy_match_percentage = len(matches['cosy']) / len(compound_peaks['cosy']) if len(compound_peaks['cosy']) > 0 else None
        hmbc_match_percentage = len(matches['hmbc']) / len(compound_peaks['hmbc']) if len(compound_peaks['hmbc']) > 0 else None

        # Calculate overall match score.
        # This is the average of the individual spectrum match percentages.
        # Only include types where the compound actually has peaks.
        scores_to_average = []
        if hsqc_match_percentage is not None:
            scores_to_average.append(hsqc_match_percentage)
        if cosy_match_percentage is not None:
            scores_to_average.append(cosy_match_percentage)
        if hmbc_match_percentage is not None:
            scores_to_average.append(hmbc_match_percentage)

        match_score = np.mean(scores_to_average) if scores_to_average else 0.0


        logger.debug(f"  Compound: {compound_name}")
        # Corrected f-strings to handle None values gracefully
        logger.debug(f"    HSQC Matches: {len(matches['hsqc'])}/{len(compound_peaks['hsqc'])} (Score: {hsqc_match_percentage:.2f}" if hsqc_match_percentage is not None else f"    HSQC Matches: {len(matches['hsqc'])}/{len(compound_peaks['hsqc'])} (Score: N/A)")
        logger.debug(f"    COSY Matches: {len(matches['cosy'])}/{len(compound_peaks['cosy'])} (Score: {cosy_match_percentage:.2f}" if cosy_match_percentage is not None else f"    COSY Matches: {len(matches['cosy'])}/{len(compound_peaks['cosy'])} (Score: N/A)")
        logger.debug(f"    HMBC Matches: {len(matches['hmbc'])}/{len(compound_peaks['hmbc'])} (Score: {hmbc_match_percentage:.2f}" if hmbc_match_percentage is not None else f"    HMBC Matches: {len(matches['hmbc'])}/{len(compound_peaks['hmbc'])} (Score: N/A)")
        logger.debug(f"    Overall Match Score: {match_score:.2f}")

        # The new algorithm uses a 10% threshold for the *overall* match score.
        if match_score >= 0.10: 
            logger.debug(f"  !!! Match Found for {compound_name} with overall score {match_score:.2f} !!!")
            results.append({
                'compound': copy.deepcopy(compound), # Deep copy the compound dictionary to ensure JSON serializability
                'match_score': match_score,
                'details': {
                    'hsqc_matches': f"{len(matches['hsqc'])}/{len(compound_peaks['hsqc'])}",
                    'cosy_matches': f"{len(matches['cosy'])}/{len(compound_peaks['cosy'])}",
                    'hmbc_matches': f"{len(matches['hmbc'])}/{len(compound_peaks['hmbc'])}",
                    'hsqc_percentage': hsqc_match_percentage, # Added
                    'cosy_percentage': cosy_match_percentage, # Added
                    'hmbc_percentage': hmbc_match_percentage  # Added
                }
            })
        else:
            logger.debug(f"  No match for {compound_name} (overall score {match_score:.2f} < 0.10 threshold).")

    # Calculate truly unmatched sample peaks across all detected compounds
    # Transform list of dictionaries to list of lists [H, C] or [H1, H2]
    unmatched_hsqc_peaks = [
        [peak['H'], peak['C']] for i, peak in enumerate(all_sample_peaks['hsqc']) if i not in overall_matched_hsqc_indices
    ]
    unmatched_cosy_peaks = [
        [peak['H1'], peak['H2']] for i, peak in enumerate(all_sample_peaks['cosy']) if i not in overall_matched_cosy_indices
    ]
    unmatched_hmbc_peaks = [
        [peak['H'], peak['C']] for i, peak in enumerate(all_sample_peaks['hmbc']) if i not in overall_matched_hmbc_indices
    ]

       # Sort by best matches first
    sorted_results = sorted(results, key=lambda x: x['match_score'], reverse=True)
    logger.debug(f"--- Finished analyze_mixture. Detected {len(sorted_results)} compounds. ---")

    # Generate plots
    hsqc_plot, cosy_plot, hmbc_plot = generate_nmr_plots(
        sample_hsqc, sample_cosy, sample_hmbc
    )

    return {
        'detected_entries': sorted_results,
        'unmatched_sample_peaks': {
            'hsqc': unmatched_hsqc_peaks,
            'cosy': unmatched_cosy_peaks,
            'hmbc': unmatched_hmbc_peaks
        }
    }, (hsqc_plot, cosy_plot, hmbc_plot)

def run_analysis(hsqc_data, cosy_data, hmbc_data, db_entries):
    """
    Wrapper function for analyze_mixture that uses default tolerances.
    """
    return analyze_mixture(hsqc_data, cosy_data, hmbc_data, db_entries)

# New API endpoint handler function
def handle_analyze_request(db_entries):
    """
    Handles the /api/analyze POST request from the frontend.
    """
    try:
        data = request.get_json()
        hsqc_data = data.get('hsqc', '').strip()
        cosy_data = data.get('cosy', '').strip()
        hmbc_data = data.get('hmbc', '').strip()

        if not hsqc_data and not cosy_data and not hmbc_data:
            return jsonify({"success": False, "error": "Please enter at least one type of NMR data."}), 400

        # Perform the analysis
        analysis_results = analyze_mixture(
            hsqc_data=hsqc_data,
            cosy_data=cosy_data,
            hmbc_data=hmbc_data,
            db_entries=db_entries
        )

        # Generate NMR plots
        hsqc_plot, cosy_plot, hmbc_plot = generate_nmr_plots(hsqc_data, cosy_data, hmbc_data)

        # Prepare the response
        response_data = {
            "success": True,
            "message": "Analysis completed successfully!",
            "data": {
                "analysis": analysis_results,
                "plots": {
                    "hsqc": hsqc_plot,
                    "cosy": cosy_plot,
                    "hmbc": hmbc_plot
                }
            }
        }

        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"Error during analysis: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500