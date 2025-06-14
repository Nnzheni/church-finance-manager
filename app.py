from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import json, os, datetime, io
import pandas as pd

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

USERS_FILE    = 'users.json'
BUDGETS_FILE  = 'budgets.json'
INCOME_LOG    = 'income_log.json'
EXPENSE_LOG   = 'expense_log.json'

def load_json(f):
    if os.path.exists(f):
        return json.load(open(f))
    return []

def save_json(f, data):
    json.dump(data, open(f, 'w'), indent=2)

def load_users():    return load_json(USERS_FILE)
def load_budgets():  return load_json(BUDGETS_FILE)

@app.route('/', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u,p = request.form['username'], request.form['password']
        users = load_users()
        if u in users and users[u]['password']==p:
            session.update(user=u, role=users[u]['role'], dept=users[u]['department'])
            return redirect(url_for('dashboard'))
        flash('Invalid credentials','danger')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect(url_for('login'))
    month = int(request.args.get('month', datetime.datetime.now().month))
    year  = int(request.args.get('year',  datetime.datetime.now().year))
    dept  = session['dept']

    inc = [e for e in load_json(INCOME_LOG)
           if e['department']==dept and
              datetime.datetime.fromisoformat(e['date']).month==month and
              datetime.datetime.fromisoformat(e['date']).year==year]
    exp = [e for e in load_json(EXPENSE_LOG)
           if e['department']==dept and
              datetime.datetime.fromisoformat(e['date']).month==month and
              datetime.datetime.fromisoformat(e['date']).year==year]

    total_inc = sum(e['amount'] for e in inc)
    total_exp = sum(e['amount'] for e in exp)
    budgets    = load_budgets()
    limit      = budgets.get(dept, 0)
    remain     = limit - total_exp

    # Chart data for all 12 months
    labels = [f"{year}-{m:02d}" for m in range(1,13)]
    inc_data = [ sum(e['amount'] for e in load_json(INCOME_LOG)
                     if e['department']==dept and
                        datetime.datetime.fromisoformat(e['date']).strftime('%Y-%m')==lbl)
                 for lbl in labels ]
    exp_data = [ sum(e['amount'] for e in load_json(EXPENSE_LOG)
                     if e['department']==dept and
                        datetime.datetime.fromisoformat(e['date']).strftime('%Y-%m')==lbl)
                 for lbl in labels ]

    return render_template('dashboard.html',
        user=session['user'], role=session['role'], dept=dept,
        month=month, year=year,
        total_inc=total_inc, total_exp=total_exp,
        limit=limit, remain=remain,
        chart_labels=labels, chart_inc=inc_data, chart_exp=exp_data
    )

@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method=='POST':
        entry = {
          'amount': float(request.form['amount']),
          'note':   request.form['note'],
          'date':   request.form['date'],
          'department': session['dept']
        }
        L=load_json(INCOME_LOG); L.append(entry); save_json(INCOME_LOG,L)
        flash('Income saved','success')
        return redirect(url_for('dashboard'))
    return render_template('add_income.html')

@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method=='POST':
        entry = {
          'amount': float(request.form['amount']),
          'note':   request.form['note'],
          'date':   request.form['date'],
          'department': session['dept']
        }
        L=load_json(EXPENSE_LOG); L.append(entry); save_json(EXPENSE_LOG,L)
        flash('Expense saved','success')
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html')

@app.route('/report', methods=['GET'])
def report():
    # Load and tag entries
    income = load_json(INCOME_LOG)
    for i in income:
        i['type'] = 'Income'
        i['description'] = i.get('note', '')

    expense = load_json(EXPENSE_LOG)
    for e in expense:
        e['type'] = 'Expense'
        e['description'] = e.get('note', '')

    combined = income + expense

    # Get filters from query string
    department_filter = request.args.get('department', '')
    from_date = request.args.get('from_date', '')
    to_date   = request.args.get('to_date', '')

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

    # Sort newest first
    filtered.sort(key=lambda x: x['date'], reverse=True)

    return render_template(
        'report.html',
        data=filtered,
        department_filter=department_filter,
        from_date=from_date,
        to_date=to_date
    )


@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

if __name__=='__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT',10000)))
