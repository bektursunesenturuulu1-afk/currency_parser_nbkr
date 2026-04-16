import pandas as pd
import requests
from io import StringIO
from datetime import datetime
import os

# Дата сегодня
today = datetime.now().date()

# Валюты
currencies = ['USD', 'EUR', 'KZT', 'CNY', 'UZS', 'RUB']

# Ссылка на курс НБКР по дате
url = f'https://www.nbkr.kg/XML/daily.xml?date={today.strftime("%d.%m.%Y")}'
response = requests.get(url)

# Чтение XML
df = pd.read_xml(StringIO(response.text))

# Переименование колонки, если нужно
if 'ISOCode' not in df.columns and 'ISO' in df.columns:
    df.rename(columns={'ISO': 'ISOCode'}, inplace=True)

# Фильтрация нужных валют
df_filtered = df[df['ISOCode'].isin(currencies)].copy()
df_filtered['Value'] = df_filtered['Value'].str.replace(',', '.').astype(float)

# Словарь с курсами
rates = df_filtered.set_index('ISOCode')['Value'].to_dict()

# Формируем строку
new_row = {'Curr': today}
for cur in currencies:
    new_row[cur] = rates.get(cur)

new_df = pd.DataFrame([new_row])

# Файл, в который сохраняем
filename = 'rates_table.xlsx'

# Если файл существует — читаем и дополняем
if os.path.exists(filename):
    existing_df = pd.read_excel(filename)

    # Преобразуем столбец даты в формат datetime.date
    existing_df['Curr'] = pd.to_datetime(existing_df['Curr']).dt.date

    # Если уже есть строка с сегодняшней датой — не добавляем
    if today in existing_df['Curr'].values:
        print(f"Курсы за {today} уже есть в файле '{filename}'. Новые данные не добавлены.")
    else:
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        combined_df.to_excel(filename, index=False)
        print(f"Курсы за {today} добавлены в файл '{filename}'.")
else:
    # Если файла нет — создаём
    new_df.to_excel(filename, index=False)
    print(f"Файл '{filename}' создан и записаны курсы за {today}.")
