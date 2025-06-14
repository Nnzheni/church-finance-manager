from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import json, os, datetime, io
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

USERS_FILE = 'users.json'
BUDGETS_FILE = 'budgets.json'

def get_google_sheet(sheet_name):
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return []

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def load_budgets():
    return load_json(BUDGETS_FILE)

def get_department_budget(dept_name):
    budgets = load_budgets()
    return budgets.get(dept_name, 0)

@app.route('/', methods=['GET','POST'])
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        if username in users and users[username]['password'] == password:
            session['user'] = username
            session['role'] = users[username]['role']
            session['department'] = users[username]['department']
            return redirect(url_for('dashboard'))
        flash("Invalid login credentials", "danger")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    dept = session['department']
    role = session['role']

    now = datetime.now()
    selected_month = int(request.args.get('month', now.month))
    selected_year = int(request.args.get('year', now.year))
    current_year = now.year

    income_log = load_json('income_log.json')
    expense_log = load_json('expense_log.json')

    # Filter this dept & month
    dept_income = [
        i for i in income_log
        if i['department'] == dept
           and datetime.strptime(i['date'], "%Y-%m-%d").month == selected_month
           and datetime.strptime(i['date'], "%Y-%m-%d").year == selected_year
    ]
    dept_expense = [
        e for e in expense_log
        if e['department'] == dept
           and datetime.strptime(e['date'], "%Y-%m-%d").month == selected_month
           and datetime.strptime(e['date'], "%Y-%m-%d").year == selected_year
    ]

    total_income = sum(i['amount'] for i in dept_income)
    total_expense = sum(e['amount'] for e in dept_expense)
    remaining_budget = get_department_budget(dept) - total_expense

    # Chart data across all 12 months
    chart_labels  = [f"{selected_year}-{m:02d}" for m in range(1,13)]
    chart_income  = [
        sum(
            i['amount']
            for i in income_log
            if i['department']==dept
               and datetime.strptime(i['date'], "%Y-%m-%d").strftime('%Y-%m')==label
        )
        for label in chart_labels
    ]
    chart_expense = [
        sum(
            e['amount']
            for e in expense_log
            if e['department']==dept
               and datetime.strptime(e['date'], "%Y-%m-%d").strftime('%Y-%m')==label
        )
        for label in chart_labels
    ]

    return render_template(
        'dashboard.html',
        user=session['user'],
        role=role,
        dept=dept,
        budget={
            'income': total_income,
            'expense': total_expense,
            'limit': get_department_budget(dept),
            'remaining': remaining_budget
        },
        total_income=total_income,
        total_expense=total_expense,
        balance=(total_income - total_expense),
        remaining_budget=remaining_budget,
        chart_labels=chart_labels,
        chart_income=chart_income,
        chart_expense=chart_expense,
        now=now,
        selected_month=selected_month,
        selected_year=selected_year,
        current_year=current_year
    )


if __name__ == '__main__':
    # Listen on the PORT provided by the environment (for Render.com etc.), default to 10000
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))



