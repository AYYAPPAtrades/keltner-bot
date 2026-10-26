name: Nifty Trading Bot Runner

on:
  workflow_dispatch:
  schedule:
    - cron: '15 3 * * 1-5'

jobs:
  run-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 420

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install yfinance pandas ta requests reportlab pytz numpy

      - name: Run Scalper Bot
        run: python scalper.py
