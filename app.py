from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_file
)
import json, os, io
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# ─── FILES ──────────────────────────────────────────────────────────────
USERS_FILE        = 'users.json'
ENTRIES_FILE      = 'entries.json'    # holds both income & expense
BUDGETS_FILE      = 'budgets.json'

# ─── UTILITIES ──────────────────────────────────────────────────────────
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path,'r') as f:
            return json.load(f)
    return default() if callable(default) else default

def save_json(path, data):
    with open(path,'w') as f:
        json.dump(data, f, indent=2)

def parse_date(s): return datetime.strptime(s, "%Y-%m-%d")

# ─── AUTH ────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET','POST'])
def login():
    if request.method=='POST':
        users = load_json(USERS_FILE, default=dict)
        u = request.form['username']
        p = request.form['password']
        if u in users and users[u]['password']==p:
            session.update({
                'user': u,
                'role': users[u]['role'],
                'dept': users[u]['department']
            })
            return redirect(url_for('dashboard'))
        flash("Invalid credentials","danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── DASHBOARD ──────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    user   = session['user']
    role   = session['role']
    dept   = session['dept']
    now    = datetime.now()

    # filters
    acct   = request.args.get('account','Main')
    m      = int(request.args.get('month', now.month))
    y      = int(request.args.get('year',  now.year))

    # load data
    entries = load_json(ENTRIES_FILE, default=list)
    budgets = load_json(BUDGETS_FILE, default=dict)

    # filter entries by account/department/date
    def keep(e):
        if role=='Senior Pastor':
            pass
        elif role=='Finance Manager':
            if acct not in ('Main','Building Fund'): return False
            if e['account']!=acct: return False
        else:
            # departmental treasurers only their own dept account
            if e['account']!=dept: return False
        d = parse_date(e['date'])
        return d.year==y and d.month==m

    month_entries = [e for e in entries if keep(e)]

    total_inc = sum(e['amount'] for e in month_entries if e['type']=='Income')
    total_exp = sum(e['amount'] for e in month_entries if e['type']=='Expense')
    balance   = total_inc - total_exp
    limit     = budgets.get(acct if role=='Finance Manager' else dept, 0.0)
    remaining = limit - total_exp

    # chart: 12 months across whole year for selected account/department
    labels = [f"{y}-{mn:02d}" for mn in range(1,13)]
    def sum_for(lbl, t):
        return sum(e['amount'] for e in entries
                   if e['type']==t
                   and e['account' if role=='Finance Manager' else 'account']==
                       (acct if role=='Finance Manager' else dept)
                   and e['date'].startswith(lbl))
    chart_inc = [sum_for(lbl,'Income') for lbl in labels]
    chart_exp = [sum_for(lbl,'Expense') for lbl in labels]

    return render_template('dashboard.html',
        user=user, role=role, dept=dept,
        now=now, selected_month=m, selected_year=y,
        current_year=now.year,
        account=acct,
        total_income=total_inc,
        total_expense=total_exp,
        balance=balance,
        budget_limit=limit,
        remaining=remaining,
        chart_labels=labels,
        chart_income=chart_inc,
        chart_expense=chart_exp
    )

# ─── NEW ENTRY (INCOME/EXPENSE) ──────────────────────────────────────────
@app.route('/add_income', methods=['GET','POST'])
def add_income():
    # … your code …
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']
    dept = session['dept']

    # only Finance Manager posts to Main/Building Fund
    # departmental treasurers to their own room
    valid_accounts = []
    if role=='Finance Manager':
        valid_accounts = ['Main','Building Fund']
    elif role=='Senior Pastor':
        valid_accounts = []  # cannot post
    else:
        valid_accounts = [dept]

    if request.method=='POST':
        acc = request.form['account']
        if acc not in valid_accounts:
            flash("Account not permitted","danger")
            return redirect(url_for('dashboard'))

        entry = {
            'type':        'Income'   if kind=='income'  else 'Expense',
            'account':     acc,
            'department':  dept,
            'category':    request.form['category'],
            'description': request.form.get('description',''),
            'date':        request.form['date'],
            'amount':      float(request.form['amount'])
        }
        entries = load_json(ENTRIES_FILE, default=list)
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)
        flash(f"{kind.title()} saved","success")
        return redirect(url_for('dashboard'))

    return render_template(
      'add_entry.html',
      kind=kind,
      valid_accounts=valid_accounts,
      now=datetime.now()
    )

# ─── BUDGET MANAGEMENT ───────────────────────────────────────────────────
@app.route('/budgets', methods=['GET','POST'])
def manage_budgets():
    if session.get('role')!='Finance Manager':
        return redirect(url_for('dashboard'))

    budgets = load_json(BUDGETS_FILE, default=dict)
    if request.method=='POST':
        for acc in ['Main','Building Fund']:
            try:
                budgets[acc] = float(request.form.get(acc, budgets.get(acc,0)))
            except:
                pass
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated","success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)

# ─── REPORT & EXPORT ─────────────────────────────────────────────────────
@app.route('/report')
def report():
    # identical to dashboard filters but no budget/chart
    return redirect(url_for('dashboard'))

@app.route('/export-excel')
def export_excel():
    return redirect(url_for('dashboard'))

# … all of your @app.route definitions …


@app.route('/export-pdf')
def export_pdf():
    # … build your `data` list …
    return render_template(
      "report_pdf.html",
      data=data,
      now=datetime.now()
    )


if __name__=='__main__':
    # Only one app.run() at the very end of the file
    app.run(
      host='0.0.0.0',
      port=int(os.environ.get('PORT',10000)),
      debug=True
    )
