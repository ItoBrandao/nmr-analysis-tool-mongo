import pandas as pd
import math
from io import StringIO

# === USER CONFIGURATION ===
delta_1H = 0.06    # ppm tolerance for 1H (chemical_shift_x)
delta_13C = 0.8    # ppm tolerance for 13C (chemical_shift_y)

database_file = "database_input.csv"  # database file name

methanol_1H_ref = 3.31  # Corrected 1H chemical shift of methanol
methanol_13C_ref = 49.1  # Corrected 13C chemical shift of methanol
# ===========================

# Load database CSV once at the top level
db_df = pd.read_csv(database_file)
db_df = db_df.dropna(subset=['chemical_shift_x', 'chemical_shift_y'])
db_df['chemical_shift_x'] = db_df['chemical_shift_x'].astype(float)
db_df['chemical_shift_y'] = db_df['chemical_shift_y'].astype(float)

def compare_peaks(hsqc_peaks_str, delta_1H=0.06, delta_13C=0.8):
    """
    Compare HSQC peaks against the database.
    
    :param hsqc_peaks_str: Multiline string containing HSQC peaks (1H, 13C, Intensity)
                            e.g., "3.35 49.7 1.0\n7.20 128 0.5"
    :param delta_1H: Tolerance for 1H shifts
    :param delta_13C: Tolerance for 13C shifts
    :return: Dictionary with fully and partially matched compounds
    """
    if not hsqc_peaks_str.strip():
        return {'fully': [], 'partial': [], 'message': 'No HSQC peaks provided for analysis.'}

    try:
        # Load HSQC peaks from string
        # Using StringIO to treat the string as a file
        # delim_whitespace=True handles multiple spaces as a single delimiter
        # header=None because the input string doesn't have a header row
        # names to assign column names
        exp_df = pd.read_csv(StringIO(hsqc_peaks_str),
                             delim_whitespace=True,
                             header=None,
                             names=['1H', '13C', 'Intensity'])
    except Exception as e:
        return {'fully': [], 'partial': [], 'message': f'Error parsing HSQC peaks string: {e}'}

    # Clean and convert to float
    # Drop rows where '1H' or '13C' are NaN after parsing (e.g., malformed lines)
    exp_df = exp_df.dropna(subset=['1H', '13C'])
    
    # Ensure Intensity column exists and is float, default to 1.0 if missing
    if 'Intensity' not in exp_df.columns:
        exp_df['Intensity'] = 1.0
    exp_df['Intensity'] = exp_df['Intensity'].astype(float)

    exp_df['1H'] = exp_df['1H'].astype(float)
    exp_df['13C'] = exp_df['13C'].astype(float)

    # Calibration using the most intense peak
    if not exp_df.empty and 'Intensity' in exp_df.columns:
        most_intense_peak = exp_df.loc[exp_df['Intensity'].idxmax()]
        most_intense_peak_1H = most_intense_peak['1H']
        most_intense_peak_13C = most_intense_peak['13C']

        calibration_shift_1H = methanol_1H_ref - most_intense_peak_1H
        calibration_shift_13C = methanol_13C_ref - most_intense_peak_13C

        exp_df['1H_calibrated'] = exp_df['1H'] + calibration_shift_1H
        exp_df['13C_calibrated'] = exp_df['13C'] + calibration_shift_13C

        # print(f"Most intense peak found at 1H: {most_intense_peak_1H:.4f} ppm, 13C: {most_intense_peak_13C:.4f} ppm.")
        # print(f"1H chemical shifts calibrated by: {calibration_shift_1H:.4f} ppm")
        # print(f"13C chemical shifts calibrated by: {calibration_shift_13C:.4f} ppm")
    else:
        # print("Warning: 'Intensity' column not found or experimental data is empty. Skipping calibration.")
        exp_df['1H_calibrated'] = exp_df['1H']
        exp_df['13C_calibrated'] = exp_df['13C']

    # Group reference peaks by compound from the globally loaded db_df
    compound_groups = db_df.groupby('database_id')

    fully_matched = []
    partially_matched = []

    def peak_matches(ref_peak, experimental_peaks):
        """Check if ref_peak matches any of the calibrated experimental peaks within tolerance."""
        for _, exp_peak in experimental_peaks.iterrows():
            if (
                abs(ref_peak['chemical_shift_x'] - exp_peak['1H_calibrated']) <= delta_1H and
                abs(ref_peak['chemical_shift_y'] - exp_peak['13C_calibrated']) <= delta_13C
            ):
                return True
        return False

    # Compare each compound
    for compound_id, group in compound_groups:
        total_peaks = len(group)
        matched_peaks = 0

        for _, ref_peak in group.iterrows():
            if peak_matches(ref_peak, exp_df):
                matched_peaks += 1

        if matched_peaks == total_peaks:
            fully_matched.append(compound_id)
        elif matched_peaks > 0:
            match_percentage = (matched_peaks / total_peaks) * 100
            # Only add to partially_matched if the percentage is >= 50%
            if match_percentage >= 50:
                partially_matched.append((compound_id, f"{matched_peaks}/{total_peaks}", f"{match_percentage:.2f}%"))

    # Return results as a dictionary
    return {
        'fully': fully_matched,
        'partial': partially_matched
    }

# Example usage (for standalone testing)
if __name__ == "__main__":
    # Create a dummy database_input.csv for testing
    dummy_db_data = {
        'database_id': ['compoundA', 'compoundA', 'compoundB', 'compoundB', 'compoundC'],
        'chemical_shift_x': [3.30, 7.25, 3.32, 7.15, 5.00],
        'chemical_shift_y': [49.0, 128.1, 49.2, 128.0, 100.0],
        'peak_type': ['hsqc', 'hsqc', 'hsqc', 'hsqc', 'hsqc']
    }
    pd.DataFrame(dummy_db_data).to_csv("database_input.csv", index=False)

    print("--- Test Case 1: Perfect Match ---")
    hsqc_peaks_str_1 = """3.35 49.7 1.0
7.20 128.1 0.5""" # These should match compoundA after calibration
    results_1 = compare_peaks(hsqc_peaks_str_1)
    print("Fully matched compounds:", results_1['fully'])
    print("Partially matched compounds:", results_1['partial'])
    # Expected: Fully matched compounds: ['compoundA']

    print("\n--- Test Case 2: Partial Match ---")
    hsqc_peaks_str_2 = """3.35 49.7 1.0
1.00 20.0 0.2""" # Only one peak matches compoundA
    results_2 = compare_peaks(hsqc_peaks_str_2)
    print("Fully matched compounds:", results_2['fully'])
    print("Partially matched compounds:", results_2['partial'])
    # Expected: Partially matched compounds: [('compoundA', '1/2', '50.00%')]

    print("\n--- Test Case 3: No Match ---")
    hsqc_peaks_str_3 = """1.0 10.0 1.0
2.0 20.0 0.5"""
    results_3 = compare_peaks(hsqc_peaks_str_3)
    print("Fully matched compounds:", results_3['fully'])
    print("Partially matched compounds:", results_3['partial'])
    # Expected: Fully matched compounds: []
    # Expected: Partially matched compounds: []

    print("\n--- Test Case 4: Empty Input ---")
    hsqc_peaks_str_4 = ""
    results_4 = compare_peaks(hsqc_peaks_str_4)
    print("Fully matched compounds:", results_4['fully'])
    print("Partially matched compounds:", results_4['partial'])
    print("Message:", results_4['message'])
    # Expected: Message: No HSQC peaks provided for analysis.

    print("\n--- Test Case 5: Malformed Input ---")
    hsqc_peaks_str_5 = """3.35 49.7
malformed line here
7.20 128.1 0.5"""
    results_5 = compare_peaks(hsqc_peaks_str_5)
    print("Fully matched compounds:", results_5['fully'])
    print("Partially matched compounds:", results_5['partial'])
    print("Message:", results_5['message'])
    # Expected: Message: Error parsing HSQC peaks string: Expected 3 fields in parsed line, saw 2.