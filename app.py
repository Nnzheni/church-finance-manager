
from flask import Flask, render_template, request, redirect, url_for, session, flash
import json, os, datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

USERS_FILE = 'users.json'

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

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template(
        'dashboard.html',
        user=session['user'],
        role=session['role'],
        dept=session['department']
    )

@app.route('/add-income', methods=['GET', 'POST'])
def add_income():
    if 'user' not in session or session['role'] != 'Finance Manager':
        return redirect(url_for('login'))
    if request.method == 'POST':
        entry = {
            'amount': float(request.form['amount']),
            'note': request.form['note'],
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'department': session['department']
        }
        income_log = load_json('income_log.json')
        income_log.append(entry)
        save_json('income_log.json', income_log)
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
        flash('Expense recorded successfully', 'success')
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
    from flask import request

@app.route('/report', methods=['GET', 'POST'])
def report():
    # Load logs from JSON files or memory (use your actual source here)
    try:
        with open('income.json') as f:
            income_log = json.load(f)
    except:
        income_log = []

    try:
        with open('expense.json') as f:
            expense_log = json.load(f)
    except:
        expense_log = []

    # Filter form inputs
    department_filter = request.args.get('department', '')
    from_date = request.args.get('from_date', '')
    to_date = request.args.get('to_date', '')

    # Normalize income
    for i in income_log:
        i['type'] = 'Income'
        i['description'] = i.get('note', '')
    # Normalize expenses
    for e in expense_log:
        e['type'] = 'Expense'
        e['description'] = e.get('category', '')

    combined = income_log + expense_log

    # Apply filters
    filtered = []
    for entry in combined:
        if department_filter and department_filter.lower() not in entry['department'].lower():
            continue
        if from_date and entry['date'] < from_date:
            continue
        if to_date and entry['date'] > to_date:
            continue
        filtered.append(entry)

    # Sort by date (most recent first)
    filtered.sort(key=lambda x: x['date'], reverse=True)

    return render_template("report.html", data=filtered, department_filter=department_filter,
                           from_date=from_date, to_date=to_date)
@app.route('/report')
def report():
    return "✅ Report page is active!"



