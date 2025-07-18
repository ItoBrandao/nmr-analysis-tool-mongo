import pandas as pd
import math

# === USER CONFIGURATION ===
delta_1H = 0.06    # ppm tolerance for 1H (chemical_shift_x)
delta_13C = 0.8    # ppm tolerance for 13C (chemical_shift_y)

database_file = "database_input.csv"  # database file name
sample_file = "sample.csv"          # experimental (sample) peaks file name

methanol_1H_ref = 3.31  # Corrected 1H chemical shift of methanol
methanol_13C_ref = 49.1  # Corrected 13C chemical shift of methanol
# ===========================

# Load CSVs
db_df = pd.read_csv(database_file)
exp_df = pd.read_csv(sample_file, sep=';')
exp_df.columns = exp_df.columns.str.strip()

# Clean and convert to float
db_df = db_df.dropna(subset=['chemical_shift_x', 'chemical_shift_y'])
exp_df = exp_df.dropna(subset=['1H', '13C', 'Intensity']) # Ensure Intensity is not NaN
exp_df['Intensity'] = exp_df['Intensity'].astype(float)
db_df['chemical_shift_x'] = db_df['chemical_shift_x'].astype(float)
db_df['chemical_shift_y'] = db_df['chemical_shift_y'].astype(float)
exp_df['1H'] = exp_df['1H'].astype(float)
exp_df['13C'] = exp_df['13C'].astype(float)

# --- Methanol Calibration (using intensity) ---
if 'Intensity' in exp_df.columns:
    most_intense_peak = exp_df.loc[exp_df['Intensity'].idxmax()]
    most_intense_peak_1H = most_intense_peak['1H']
    most_intense_peak_13C = most_intense_peak['13C']

    calibration_shift_1H = methanol_1H_ref - most_intense_peak_1H
    calibration_shift_13C = methanol_13C_ref - most_intense_peak_13C

    exp_df['1H_calibrated'] = exp_df['1H'] + calibration_shift_1H
    exp_df['13C_calibrated'] = exp_df['13C'] + calibration_shift_13C

    print(f"Most intense peak found at 1H: {most_intense_peak_1H:.4f} ppm, 13C: {most_intense_peak_13C:.4f} ppm.")
    print(f"1H chemical shifts calibrated by: {calibration_shift_1H:.4f} ppm")
    print(f"13C chemical shifts calibrated by: {calibration_shift_13C:.4f} ppm")
else:
    print("Warning: 'Intensity' column not found in sample data. Skipping calibration.")
    exp_df['1H_calibrated'] = exp_df['1H']
    exp_df['13C_calibrated'] = exp_df['13C']

# Group reference peaks by compound
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
        if match_percentage >= 50:
            partially_matched.append((compound_id, f"{matched_peaks}/{total_peaks}", f"{match_percentage:.2f}%"))

# Output to CSV
pd.DataFrame({'database_id': fully_matched}).to_csv("fully_matched_compounds.csv", index=False)

partial_df = pd.DataFrame(partially_matched, columns=['database_id', 'matched_peaks/total_peaks', 'match_percentage'])
partial_df.to_csv("partially_matched_compounds.csv", index=False)

# Summary
print("\n✅ Done!")
print(f"Fully matched compounds: {len(fully_matched)}")
print(f"Partially matched compounds (>= 50%): {len(partially_matched)}")

if __name__ == "__main__":
    # original CLI behaviour if you ever run it standalone
    import sys
    if len(sys.argv) > 1:
        sample_file = sys.argv[1]
        compare_peaks(sample_file)