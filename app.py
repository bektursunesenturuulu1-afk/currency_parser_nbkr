from flask import Flask, jsonify, render_template, request
import pandas as pd
import requests
from io import StringIO
from datetime import datetime
import os
import math

app = Flask(__name__)

CURRENCIES = ['USD', 'EUR', 'KZT', 'CNY', 'UZS', 'RUB']
FILENAME = 'rates_table.xlsx'

CURRENCY_META = {
    'USD': {'name': 'US Dollar',       'flag': '🇺🇸', 'color': '#4ade80'},
    'EUR': {'name': 'Euro',            'flag': '🇪🇺', 'color': '#60a5fa'},
    'KZT': {'name': 'Kazakhstani Tenge','flag': '🇰🇿', 'color': '#f59e0b'},
    'CNY': {'name': 'Chinese Yuan',    'flag': '🇨🇳', 'color': '#f87171'},
    'UZS': {'name': 'Uzbek Sum',       'flag': '🇺🇿', 'color': '#c084fc'},
    'RUB': {'name': 'Russian Ruble',   'flag': '🇷🇺', 'color': '#34d399'},
}


def fetch_rates(date=None):
    """Fetch rates from NBKR XML for a given date (defaults to today)."""
    if date is None:
        date = datetime.now().date()
    url = f'https://www.nbkr.kg/XML/daily.xml?date={date.strftime("%d.%m.%Y")}'
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    # NBKR XML is encoded in windows-1251
    response.encoding = 'windows-1251'

    df = pd.read_xml(StringIO(response.text))

    if 'ISOCode' not in df.columns and 'ISO' in df.columns:
        df.rename(columns={'ISO': 'ISOCode'}, inplace=True)

    df_filtered = df[df['ISOCode'].isin(CURRENCIES)].copy()
    df_filtered['Value'] = df_filtered['Value'].astype(str).str.replace(',', '.').astype(float)

    rates = df_filtered.set_index('ISOCode')['Value'].to_dict()
    return rates


def save_rates(date, rates):
    """Save fetched rates to Excel, avoiding duplicates."""
    new_row = {'Curr': date}
    for cur in CURRENCIES:
        new_row[cur] = rates.get(cur)
    new_df = pd.DataFrame([new_row])

    if os.path.exists(FILENAME):
        existing_df = pd.read_excel(FILENAME)
        existing_df['Curr'] = pd.to_datetime(existing_df['Curr']).dt.date
        if date in existing_df['Curr'].values:
            return False  # already exists
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        combined_df.to_excel(FILENAME, index=False)
    else:
        new_df.to_excel(FILENAME, index=False)
    return True


def nan_to_none(value):
    """Convert float NaN to None so JSON stays valid."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def load_history():
    """Load history from Excel, return as list of dicts (NaN → None)."""
    if not os.path.exists(FILENAME):
        return []
    df = pd.read_excel(FILENAME)
    df['Curr'] = pd.to_datetime(df['Curr']).dt.strftime('%Y-%m-%d')
    df = df.sort_values('Curr', ascending=False)
    # Replace NaN with None so Flask's jsonify produces valid JSON (null, not NaN)
    records = df.to_dict(orient='records')
    return [
        {k: nan_to_none(v) for k, v in row.items()}
        for row in records
    ]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html',
                           currencies=CURRENCIES,
                           meta=CURRENCY_META)


@app.route('/api/fetch', methods=['POST'])
def api_fetch():
    """Fetch today's rates from NBKR and save to Excel."""
    try:
        today = datetime.now().date()
        rates = fetch_rates(today)
        added = save_rates(today, rates)
        return jsonify({
            'success': True,
            'date': str(today),
            'rates': rates,
            'added': added,
            'message': f"Rates for {today} {'saved' if added else 'already exist in file'}."
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/rates/today')
def api_today():
    """Return today's rates (fetch live, don't save)."""
    try:
        today = datetime.now().date()
        rates = fetch_rates(today)
        return jsonify({'success': True, 'date': str(today), 'rates': rates})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/history')
def api_history():
    """Return full saved history."""
    try:
        data = load_history()
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/chart/<currency>')
def api_chart(currency):
    """Return chart data for a specific currency (last 30 days)."""
    if currency not in CURRENCIES:
        return jsonify({'success': False, 'error': 'Invalid currency'}), 400
    try:
        data = load_history()
        data = sorted(data, key=lambda x: x['Curr'])[-30:]  # last 30 records
        labels = [row['Curr'] for row in data]
        values = [nan_to_none(row.get(currency)) for row in data]
        return jsonify({'success': True, 'labels': labels, 'values': values, 'currency': currency})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5050)
