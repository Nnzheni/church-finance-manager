from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import json, os, datetime, io
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def get_gsheet(sheet_name):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1  # Open the first worksheet


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

USERS_FILE = 'users.json'
BUDGETS_FILE = 'budgets.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}
def get_google_sheet(sheet_name):
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1  # Adjust sheet1 if you’re using other sheets
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return []

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
        BUDGETS_FILE = 'budgets.json'

def load_budgets():
    return load_json(BUDGETS_FILE)

def get_department_budget(dept_name):
    budgets = load_budgets()
    return budgets.get(dept_name, 0)  # Default to 0 if not found

@app.route('/', methods=['GET', 'POST'])
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
def calculate_budget():
    income_data = load_json('income_log.json')
    expense_data = load_json('expense_log.json')

    current_month = datetime.datetime.now().strftime('%Y-%m')

    total_income = sum(i['amount'] for i in income_data if i['date'].startswith(current_month))
    total_expense = sum(e['amount'] for e in expense_data if e['date'].startswith(current_month))

    budget_limit = total_income  # You can adjust this to a fixed amount if needed
    remaining = budget_limit - total_expense

    return {
        'income': round(total_income, 2),
        'expense': round(total_expense, 2),
        'limit': round(budget_limit, 2),
        'remaining': round(remaining, 2)
    }

from collections import defaultdict

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    dept = session['department']
    month = request.args.get('month', datetime.datetime.now().month, type=int)
    year = request.args.get('year', datetime.datetime.now().year, type=int)
    budget = get_department_budget(dept)

    income_log = load_json('income_log.json')
    expense_log = load_json('expense_log.json')

    dept_income = [i for i in income_log if i['department'] == dept]
    dept_expense = [e for e in expense_log if e['department'] == dept]

    # Filter by selected month/year
    filtered_income = [i for i in dept_income if datetime.datetime.strptime(i['date'], '%Y-%m-%d %H:%M:%S').month == month and datetime.datetime.strptime(i['date'], '%Y-%m-%d %H:%M:%S').year == year]
    filtered_expense = [e for e in dept_expense if datetime.datetime.strptime(e['date'], '%Y-%m-%d %H:%M:%S').month == month and datetime.datetime.strptime(e['date'], '%Y-%m-%d %H:%M:%S').year == year]

    total_income = sum(i['amount'] for i in filtered_income)
    total_expense = sum(e['amount'] for e in filtered_expense)
    balance = total_income - total_expense
    remaining_budget = budget - total_expense

    # Group monthly totals
    monthly_totals = defaultdict(lambda: {"income": 0, "expense": 0})
    for i in dept_income:
        d = datetime.datetime.strptime(i['date'], '%Y-%m-%d %H:%M:%S')
        key = f"{d.year}-{d.month:02d}"
        monthly_totals[key]['income'] += i['amount']
    for e in dept_expense:
        d = datetime.datetime.strptime(e['date'], '%Y-%m-%d %H:%M:%S')
        key = f"{d.year}-{d.month:02d}"
        monthly_totals[key]['expense'] += e['amount']

    chart_labels = sorted(monthly_totals.keys())
    chart_income = [monthly_totals[m]['income'] for m in chart_labels]
    chart_expense = [monthly_totals[m]['expense'] for m in chart_labels]

    return render_template(
        'dashboard.html',
        user=session['user'],
        role=session['role'],
        dept=dept,
        month=month,
        year=year,
        budget={
            "limit": budget,
            "income": total_income,
            "expense": total_expense,
            "remaining": remaining_budget
        },
        chart_labels=chart_labels,
        chart_income=chart_income,
        chart_expense=chart_expense
    )



@app.route('/add-income', methods=['GET', 'POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount = float(request.form['amount'])
        note = request.form['note']
        date = request.form['date']
        department = session['department']

        entry = {
            'amount': amount,
            'note': note,
            'date': date,
            'department': department
        }

        # Save to local JSON
        income_log = load_json('income_log.json')
        income_log.append(entry)
        save_json('income_log.json', income_log)

        # Save to Google Sheet
        try:
            sheet = get_google_sheet("AFM Finance Income")  # Replace with your actual sheet name
            sheet.append_row([
                entry['amount'],
                entry['note'],
                entry['date'],
                entry['department']
            ])
        except Exception as e:
            print("Google Sheets error (income):", e)

        flash('Income recorded successfully', 'success')
        return redirect(url_for('dashboard'))

    return render_template('add_income.html')


@app.route('/add-expense', methods=['GET', 'POST'])
def add_expense():
    if 'user' not in session or session['role'] != 'Finance Manager':
        return redirect(url_for('login'))
    if request.method == 'POST':
        entry = {
            'amount': float(request.form['amount']),
            'category': request.form['category'],
            'note': request.form['note'],
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'department': session['department']
        }
        expense_log = load_json('expense_log.json')
        expense_log.append(entry)
        save_json('expense_log.json', expense_log)
        # ✅ Sync to Google Sheet
try:
    sheet = get_google_sheet("AFM Finance Expense")  # Replace with your actual sheet name
    sheet.append_row([
        entry['amount'],
        entry['category'],
        entry['note'],
        entry['date'],
        entry['department']
    ])
except Exception as e:
    print("Google Sheets error (expense):", e)
        flash('Expense recorded successfully', 'success')
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
@app.route('/budgets', methods=['GET', 'POST'])
def manage_budgets():
    if 'user' not in session or session['role'] != 'Finance Manager':
        return redirect(url_for('login'))

    budgets = load_json('budgets.json')

    if request.method == 'POST':
        for dept in budgets:
            try:
                budgets[dept] = float(request.form.get(dept, budgets[dept]))
            except ValueError:
                pass  # skip invalid inputs
        save_json('budgets.json', budgets)
        flash("Budgets updated successfully", "success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)


@app.route('/report', methods=['GET'])
def report():
    income_log = load_json('income_log.json')
    expense_log = load_json('expense_log.json')

    for i in income_log:
        i['type'] = 'Income'
        i['description'] = i.get('note', '')
    for e in expense_log:
        e['type'] = 'Expense'
        e['description'] = e.get('category', '')

    combined = income_log + expense_log

    department_filter = request.args.get('department', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    filtered = []
    for entry in combined:
        if department_filter and department_filter.lower() not in entry['department'].lower():
            continue
        if from_date and entry['date'] < from_date:
            continue
        if to_date and entry['date'] > to_date:
            continue
        filtered.append(entry)

    filtered.sort(key=lambda x: x['date'], reverse=True)

    return render_template("report.html", data=filtered,
                           department_filter=department_filter,
                           from_date=from_date, to_date=to_date)

@app.route('/export-excel')
def export_excel():
    department = request.args.get('department', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    income = load_json('income_log.json')
    expenses = load_json('expense_log.json')

    for i in income:
        i['type'] = 'Income'
        i['description'] = i.get('note', '')
    for e in expenses:
        e['type'] = 'Expense'
        e['description'] = e.get('category', '')

    combined = income + expenses
    filtered = []

    for entry in combined:
        if department and department.lower() not in entry['department'].lower():
            continue
        if from_date and entry['date'] < from_date:
            continue
        if to_date and entry['date'] > to_date:
            continue
        filtered.append(entry)

    df = pd.DataFrame(filtered)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Finance Report')

    output.seek(0)
    return send_file(output, download_name="finance_report.xlsx", as_attachment=True)

@app.route('/export-pdf')
def export_pdf():
    from datetime import datetime

    department = request.args.get('department', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    income = load_json('income_log.json')
    expenses = load_json('expense_log.json')

    for i in income:
        i['type'] = 'Income'
        i['description'] = i.get('note', '')
    for e in expenses:
        e['type'] = 'Expense'
        e['description'] = e.get('category', '')

    combined = income + expenses
    filtered = []

    for entry in combined:
        if department and department.lower() not in entry['department'].lower():
            continue
        if from_date and entry['date'] < from_date:
            continue
        if to_date and entry['date'] > to_date:
            continue
        filtered.append(entry)

    filtered.sort(key=lambda x: x['date'], reverse=True)
    return render_template("report_pdf.html", data=filtered, now=datetime.now)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
