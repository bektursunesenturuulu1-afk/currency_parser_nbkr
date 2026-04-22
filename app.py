from flask import Flask, jsonify, render_template, request
import pandas as pd
import requests
from io import StringIO
from datetime import datetime, timedelta
import os
import math
from sqlalchemy import create_engine, inspect

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

# ── Database Setup ────────────────────────────────────────────────────────────
db_url = os.environ.get("DATABASE_URL", "sqlite:///rates.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)

def migrate_from_excel_if_needed():
    """Initial migration from excel file to database if DB is empty."""
    inspector = inspect(engine)
    if not inspector.has_table("rates"):
        if os.path.exists(FILENAME):
            print(f"Migrating from {FILENAME} to DB...")
            df = pd.read_excel(FILENAME)
            # Ensure Curr is date
            df['Curr'] = pd.to_datetime(df['Curr']).dt.date
            df.to_sql("rates", engine, index=False, if_exists="append")
            print("Migration complete.")
        else:
            print("No excel file to migrate, starting fresh.")

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
    """Save fetched rates to Database, avoiding duplicates."""
    new_row = {'Curr': date}
    for cur in CURRENCIES:
        new_row[cur] = rates.get(cur)
    new_df = pd.DataFrame([new_row])

    try:
        existing_df = pd.read_sql("rates", engine)
        existing_df['Curr'] = pd.to_datetime(existing_df['Curr']).dt.date
        if date in existing_df['Curr'].values:
            return False  # already exists
        new_df.to_sql("rates", engine, index=False, if_exists="append")
    except Exception:
        # Table might not exist yet
        new_df.to_sql("rates", engine, index=False, if_exists="replace")
    return True


def nan_to_none(value):
    """Convert float NaN to None so JSON stays valid."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def load_history():
    """Load history from DB, return as list of dicts (NaN → None)."""
    try:
        df = pd.read_sql("rates", engine)
        df['Curr'] = pd.to_datetime(df['Curr']).dt.strftime('%Y-%m-%d')
        df = df.sort_values('Curr', ascending=False)
        # Replace NaN with None so Flask's jsonify produces valid JSON (null, not NaN)
        records = df.to_dict(orient='records')
        return [
            {k: nan_to_none(v) for k, v in row.items()}
            for row in records
        ]
    except Exception:
        return []

def sync_missing_dates():
    """Find dates missed between the last fetched date in DB and today, and fetch them."""
    today = datetime.now().date()
    history = load_history()
    
    if history:
        latest_date_str = history[0]['Curr']
        latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d').date()
        
        current_date = latest_date + timedelta(days=1)
        while current_date <= today:
            print(f"Auto-syncing missing date: {current_date}")
            try:
                rates = fetch_rates(current_date)
                save_rates(current_date, rates)
            except Exception as e:
                print(f"Failed to fetch historical rates for {current_date}: {e}")
            current_date += timedelta(days=1)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html',
                           currencies=CURRENCIES,
                           meta=CURRENCY_META)


@app.route('/api/fetch', methods=['POST'])
def api_fetch():
    """Fetch today's rates from NBKR and save to DB. Syncs intermediate dates too."""
    try:
        migrate_from_excel_if_needed()
        # This will fetch any missed days including today if it was missed
        sync_missing_dates()
        
        today = datetime.now().date()
        rates = fetch_rates(today)
        added = save_rates(today, rates)
        return jsonify({
            'success': True,
            'date': str(today),
            'rates': rates,
            'added': added,
            'message': f"Rates for {today} {'saved' if added else 'already exist'}."
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
    # Use the port provided by Render's environment variable, or default to 5050 for local development
    port = int(os.environ.get("PORT", 5050))
    # Bind to 0.0.0.0 so the app is accessible from the outside.
    # Debug is set to False for production safety.
    app.run(host='0.0.0.0', port=port, debug=False)
