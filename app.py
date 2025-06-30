from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import json, os, io
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# ─── FILE PATHS ────────────────────────────────────────────────────────────────
USERS_FILE       = 'users.json'
INCOME_LOG_FILE  = 'income_log.json'
EXPENSE_LOG_FILE = 'expense_log.json'
BUDGETS_FILE     = 'budgets.json'

# ─── UTILITIES ────────────────────────────────────────────────────────────────
def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return []    # Always return a list for logs

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

def get_department_budget(dept):
    budgets = {}
    raw = load_json(BUDGETS_FILE)
    if isinstance(raw, dict):
        budgets = raw
    return budgets.get(dept, 0.0)

# ─── AUTH ROUTES ───────────────────────────────────────────────────────────────
@app.route('/', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        users = load_json(USERS_FILE)
        u = request.form['username']
        p = request.form['password']
        if u in users and users[u]['password'] == p:
            session['user']       = u
            session['role']       = users[u]['role']
            session['department'] = users[u]['department']
            return redirect(url_for('dashboard'))
        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    dept = session['department']
    role = session['role']
    now  = datetime.now()

    # month/year filter
    m = int(request.args.get('month', now.month))
    y = int(request.args.get('year',  now.year))

    incomes  = load_json(INCOME_LOG_FILE)
    expenses = load_json(EXPENSE_LOG_FILE)

    # filter by dept & date
    dept_inc = [
        i for i in incomes
        if i['department']==dept
        and parse_date(i['date']).month==m
        and parse_date(i['date']).year==y
    ]
    dept_exp = [
        e for e in expenses
        if e['department']==dept
        and parse_date(e['date']).month==m
        and parse_date(e['date']).year==y
    ]

    total_income  = sum(i['amount'] for i in dept_inc)
    total_expense = sum(e['amount'] for e in dept_exp)
    balance       = total_income - total_expense

    limit     = get_department_budget(dept)
    remaining = limit - total_expense

    # Build chart data (12 months of this year)
    labels    = [f"{y}-{mn:02d}" for mn in range(1,13)]
    chart_inc = [
        sum(i['amount'] for i in incomes
            if i['department']==dept and i['date'].startswith(lbl))
        for lbl in labels
    ]
    chart_exp = [
        sum(e['amount'] for e in expenses
            if e['department']==dept and e['date'].startswith(lbl))
        for lbl in labels
    ]

    return render_template('dashboard.html',
        user=session['user'],
        dept=dept,
        role=role,
        now=now,
        selected_month=m,
        selected_year=y,
        current_year=now.year,
        budget={ 'income': total_income,
                 'expense': total_expense,
                 'limit':   limit,
                 'remaining': remaining },
        chart_labels=labels,
        chart_income=chart_inc,
        chart_expense=chart_exp
    )

# ─── ADD INCOME ───────────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        entry = {
            'amount':     float(request.form['amount']),
            'note':       request.form['note'],
            'date':       request.form['date'],
            'department': session['department']
        }
        log = load_json(INCOME_LOG_FILE)
        log.append(entry)
        save_json(INCOME_LOG_FILE, log)
        flash("Income saved", "success")
        return redirect(url_for('dashboard'))
    return render_template('add_income.html')

# ─── ADD EXPENSE ──────────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        entry = {
            'amount':     float(request.form['amount']),
            'category':   request.form.get('category',''),
            'note':       request.form.get('note',''),
            'date':       request.form['date'],
            'department': session['department']
        }
        log = load_json(EXPENSE_LOG_FILE)
        log.append(entry)
        save_json(EXPENSE_LOG_FILE, log)
        flash("Expense saved", "success")
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html')

# ─── MANAGE BUDGETS ───────────────────────────────────────────────────────────
@app.route('/budgets', methods=['GET','POST'])
def manage_budgets():
    if 'user' not in session or session['role'] != 'Finance Manager':
        return redirect(url_for('login'))

    budgets = {}
    raw     = load_json(BUDGETS_FILE)
    if isinstance(raw, dict):
        budgets = raw

    if request.method == 'POST':
        for dept_name in budgets.keys():
            try:
                budgets[dept_name] = float(request.form.get(dept_name, budgets[dept_name]))
            except ValueError:
                pass
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated", "success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)

# ─── FINANCE REPORT ──────────────────────────────────────────────────────────
@app.route('/report')
def report():
    dept_f = request.args.get('department','').lower()
    frm    = request.args.get('from_date','')
    to     = request.args.get('to_date','')

    incomes  = load_json(INCOME_LOG_FILE)
    expenses = load_json(EXPENSE_LOG_FILE)

    # tag and unify
    for i in incomes:
        i['type']        = 'Income'
        i['description'] = i.get('note','')
    for e in expenses:
        e['type']        = 'Expense'
        e['description'] = e.get('note', e.get('category',''))

    combined = incomes + expenses

    def keep(r):
        if dept_f    and dept_f not in r['department'].lower(): return False
        if frm       and r['date'] < frm: return False
        if to        and r['date'] > to:  return False
        return True

    data = list(filter(keep, combined))
    data.sort(key=lambda x: x['date'], reverse=True)

    return render_template('report.html',
        data=data,
        department_filter=request.args.get('department',''),
        from_date=frm, to_date=to
    )

# ─── EXPORT EXCEL ────────────────────────────────────────────────────────────
@app.route('/export-excel')
def export_excel():
    dept_f = request.args.get('department','')
    frm    = request.args.get('from_date','')
    to     = request.args.get('to_date','')

    # load raw lists
    incomes  = load_json(INCOME_LOG_FILE)  or []
    expenses = load_json(EXPENSE_LOG_FILE) or []
    combined = incomes + expenses

    rows = []
    for r in combined:
        # compute type & description locally
        rtype = 'Income' if 'note' in r else 'Expense'
        desc  = r.get('note') or r.get('category','')

        # apply same filters as report()
        if dept_f and dept_f.lower() not in r['department'].lower():
            continue
        if frm and r['date'] < frm:
            continue
        if to and r['date'] > to:
            continue

        rows.append({
            'Date':        r['date'],
            'Department':  r['department'],
            'Type':        rtype,
            'Description': desc,
            'Amount (R)':  r['amount']
        })

    # now build the DataFrame and send it
    df     = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    output.seek(0)

    filename = f"report_{dept_f or 'all'}_{frm}_{to}.xlsx"
    return send_file(output,
                     download_name=filename,
                     as_attachment=True)

# ─── EXPORT PDF ──────────────────────────────────────────────────────────────
@app.route('/export-pdf')
def export_pdf():
    # reuse the same filter logic as above
    dept_f = request.args.get('department','').lower()
    frm    = request.args.get('from_date','')
    to     = request.args.get('to_date','')

    combined = load_json(INCOME_LOG_FILE) + load_json(EXPENSE_LOG_FILE)
    rows = []
    for r in combined:
        if dept_f and dept_f not in r['department'].lower(): continue
        if frm    and r['date'] < frm: continue
        if to     and r['date'] > to:  continue
        rows.append(r)
    rows.sort(key=lambda x: x['date'], reverse=True)

    return render_template('report_pdf.html',
        data=rows,
        now=lambda: datetime.now()
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT', 10000)),
            debug=True)
