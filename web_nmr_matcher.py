# web_nmr_matcher.py
import os, json, io
from flask import Flask, request, render_template_string, jsonify
import pandas as pd
from compare_nmr_peaks import compare_peaks   # we will refactor it below

app = Flask(__name__)
DB_FILE = "database_input.csv"

# ------------------------------------------------------------------
#  REFACTORED version of your compare_nmr_peaks.py
#  (now returns results instead of writing CSVs)
# ------------------------------------------------------------------
def compare_peaks(sample_str,
                  delta_1H=0.06,
                  delta_13C=0.8,
                  methanol_1H_ref=3.31,
                  methanol_13C_ref=49.1):
    """
    sample_str : multiline string  "1H 13C Intensity"
                 e.g.  3.35 49.7 1.0
                       7.20 128  0.5
    returns dict with keys: fully, partial
    """
    from io import StringIO

    # --- load database ---
    db_df = pd.read_csv(DB_FILE).dropna(subset=['chemical_shift_x', 'chemical_shift_y'])
    db_df['chemical_shift_x'] = db_df['chemical_shift_x'].astype(float)
    db_df['chemical_shift_y'] = db_df['chemical_shift_y'].astype(float)

    # --- load sample ---
    exp_df = pd.read_csv(StringIO(sample_str),
                         delim_whitespace=True,
                         header=None,
                         names=['1H', '13C', 'Intensity'])
    exp_df = exp_df.dropna(subset=['1H', '13C'])
    exp_df['Intensity'] = exp_df['Intensity'].astype(float)

    # --- calibration identical to original script ---
    most = exp_df.loc[exp_df['Intensity'].idxmax()]
    calib_1H  = methanol_1H_ref  - most['1H']
    calib_13C = methanol_13C_ref - most['13C']
    exp_df['1H_cal']  = exp_df['1H']  + calib_1H
    exp_df['13C_cal'] = exp_df['13C'] + calib_13C

    # --- matching ---
    compound_groups = db_df.groupby('database_id')
    fully, partial = [], []

    for cid, grp in compound_groups:
        total = len(grp)
        hits  = 0
        for _, ref in grp.iterrows():
            hit = ((exp_df['1H_cal'] - ref['chemical_shift_x']).abs() <= delta_1H) & \
                  ((exp_df['13C_cal'] - ref['chemical_shift_y']).abs() <= delta_13C)
            if hit.any():
                hits += 1
        if hits == total:
            fully.append(cid)
        elif hits / total >= 0.5:
            partial.append({'id': cid,
                            'ratio': f"{hits}/{total}",
                            'percent': f"{hits/total*100:.1f}%"})

    return dict(fully=fully, partial=partial)

# ------------------------------------------------------------------
#  WEB ROUTES
# ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

@app.route("/api/match", methods=["POST"])
def api_match():
    payload = request.get_json()
    peaks  = payload.get("peaks", "")
    d1h    = float(payload.get("d1h", 0.06))
    d13c   = float(payload.get("d13c", 0.8))
    if not peaks.strip():
        return jsonify({"error": "No peaks provided"}), 400
    result = compare_peaks(peaks, delta_1H=d1h, delta_13C=d13c)
    return jsonify(result)

# ------------------------------------------------------------------
#  Simple HTML page (no external templates)
# ------------------------------------------------------------------
HTML_PAGE = """
<!doctype html>
<html>
<head>
  <title>NMR HSQC Matcher</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:Arial;margin:40px;background:#f9f9f9}
    textarea{width:100%;height:160px;font-family:monospace}
    label{display:block;margin-top:10px}
    button{margin-top:15px;padding:8px 18px}
    .results{margin-top:30px}
    .results ul{margin:0;padding-left:20px}
  </style>
</head>
<body>
  <h2>HSQC peak matcher</h2>
  <p>Paste your HSQC peaks (1H 13C Intensity, one per line):</p>
  <textarea id="peaks" placeholder="3.31 49.1 1.0\n7.20 128 0.5"></textarea>

  <label>1H tolerance (ppm) <input type="number" id="d1h" value="0.06" step="0.01"></label>
  <label>13C tolerance (ppm) <input type="number" id="d13c" value="0.8" step="0.1"></label>

  <button onclick="run()">Find matches</button>

  <div class="results">
    <div id="full"></div>
    <div id="part"></div>
  </div>

<script>
async function run() {
  const peaks = document.getElementById('peaks').value;
  const d1h   = document.getElementById('d1h').value;
  const d13c  = document.getElementById('d13c').value;
  const res   = await fetch('/api/match', {
                     method:'POST',
                     headers:{'Content-Type':'application/json'},
                     body: JSON.stringify({peaks, d1h, d13c})});
  const json  = await res.json();
  document.getElementById('full').innerHTML =
      '<h3>Fully matched</h3><ul>' +
      (json.fully.length ? json.fully.map(x=>'<li>'+x) : ['<li>None']) +
      '</ul>';
  document.getElementById('part').innerHTML =
      '<h3>Partial (≥50%)</h3><ul>' +
      (json.partial.length ? json.partial.map(x=>'<li>'+x.id+'  '+x.ratio+'  '+x.percent) : ['<li>None']) +
      '</ul>';
}
</script>
</body>
</html>
"""

# ------------------------------------------------------------------
if __name__ == "__main__":
    # quick sanity check
    if not os.path.isfile(DB_FILE):
        raise SystemExit(f"{DB_FILE} is missing!")
    app.run(debug=True)