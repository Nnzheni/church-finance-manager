from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
import json
import io
from datetime import datetime
import pandas as pd
# (and if you’re using SQLAlchemy)
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

# (Optional) SQLAlchemy setup if you ever move to a DB:
app.config["SQLALCHEMY_DATABASE_URI"]        = "sqlite:///data.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ─── DATA FILE PATHS ───────────────────────────────────────────
USERS_FILE       = 'users.json'
INCOME_LOG_FILE  = 'income_log.json'
EXPENSE_LOG_FILE = 'expense_log.json'
BUDGETS_FILE     = 'budgets.json'
ENTRIES_FILE     = 'entries.json'

# ─── FILES ──────────────────────────────────────────────────────────────
class Entry(db.Model):
    __tablename__ = "entries"
    id         = db.Column(db.Integer, primary_key=True)
    kind       = db.Column(db.String(10), nullable=False)    # “Income” or “Expense”
    subtype    = db.Column(db.String(50), nullable=False)    # your “type” field
    account    = db.Column(db.String(50), nullable=False)    # Main, Building Fund, or dept
    department = db.Column(db.String(50), nullable=False)
    description= db.Column(db.String(200), default="")
    date       = db.Column(db.Date, nullable=False)
    amount     = db.Column(db.Float, nullable=False)

# create the table if it doesn't exist (on first run)
with app.app_context():
    db.create_all()


# ─── UTILITIES ──────────────────────────────────────────────────────────
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path,'r') as f:
            return json.load(f)
    return default() if callable(default) else default

def save_json(path, data):
    with open(path,'w') as f:
        json.dump(data, f, indent=2)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

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

    user = session['user']
    role = session['role']
    dept = session['dept']
    now  = datetime.now()

    # — Filters from querystring —
    acct = request.args.get('account', 'Main')
    m    = int(request.args.get('month', now.month))
    y    = int(request.args.get('year',  now.year))

    # — Load data —
    entries = load_json(ENTRIES_FILE, default=list)
    budgets = load_json(BUDGETS_FILE, default=dict)

    # — Keep only the entries this user should see this month —
    def keep(entry):
        # Finance Manager may choose Main/Building Fund
        if role == 'Finance Manager':
            if acct not in ('Main', 'Building Fund'):
                return False
            if entry['account'] != acct:
                return False

        # Departmental treasurers only see their own dept
        elif role != 'Senior Pastor':
            if entry['account'] != dept:
                return False

        # Senior Pastor sees all accounts

        # Then filter by year/month
        d = parse_date(entry['date'])
        return (d.year == y and d.month == m)

    month_entries = [e for e in entries if keep(e)]

    # — Totals —
    total_income  = sum(e['amount'] for e in month_entries if e['type'] == 'Income')
    total_expense = sum(e['amount'] for e in month_entries if e['type'] == 'Expense')
    balance       = total_income - total_expense

    # Budget for this account/dept
    key = acct if role == 'Finance Manager' else dept
    budget_limit = budgets.get(key, 0.0)
    remaining    = budget_limit - total_expense

    # — Chart data for the full year —
    labels    = [f"{y}-{mn:02d}" for mn in range(1, 13)]
    def sum_for(label, t):
        return sum(
            e['amount']
            for e in entries
            if e['type'] == t
            and (role == 'Senior Pastor' or e['account'] == key)
            and e['date'].startswith(label)
        )

    chart_income  = [sum_for(lbl, 'Income')  for lbl in labels]
    chart_expense = [sum_for(lbl, 'Expense') for lbl in labels]

    return render_template(
        'dashboard.html',
        user=user,
        role=role,
        dept=dept,
        now=now,
        selected_month=m,
        selected_year=y,
        current_year=now.year,
        account=acct,
        total_income=total_income,
        total_expense=total_expense,
        balance=balance,
        budget_limit=budget_limit,
        remaining=remaining,
        chart_labels=labels,
        chart_income=chart_income,
        chart_expense=chart_expense,
    )

# ─── ADD INCOME ────────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']
    dept = session['dept']

    # Finance Manager picks, others use their dept only
    if role=='Finance Manager':
        valid_accounts = ['Main','Building Fund']
    else:
        valid_accounts = [dept]

    if request.method=='POST':
        account = (request.form['account']
                   if role=='Finance Manager'
                   else dept)
        if account not in valid_accounts:
            flash("Account not permitted","danger")
            return redirect(url_for('dashboard'))

        entry = Entry(
            kind       = "Income",
            subtype    = request.form['type'],
            account    = account,
            department = dept,
            description= request.form.get('description',''),
            date       = datetime.strptime(request.form['date'], "%Y-%m-%d"),
            amount     = float(request.form['amount'])
        )
        db.session.add(entry)
        db.session.commit()
        flash("Income saved","success")
        return redirect(url_for('dashboard'))

    return render_template(
        'add_income.html',
        valid_accounts=valid_accounts,
        role=role,
        now=datetime.now()
    )

# ─── ADD EXPENSE ───────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']
    dept = session['dept']

    # Finance Manager picks, others use their dept only
    if role=='Finance Manager':
        valid_accounts = ['Main','Building Fund']
    else:
        valid_accounts = [dept]

    if request.method=='POST':
        account = (request.form['account']
                   if role=='Finance Manager'
                   else dept)
        if account not in valid_accounts:
            flash("Account not permitted","danger")
            return redirect(url_for('dashboard'))

        entry = Entry(
            kind       = "expense",
            subtype    = request.form['type'],
            account    = account,
            department = dept,
            description= request.form.get('description',''),
            date       = datetime.strptime(request.form['date'], "%Y-%m-%d"),
            amount     = float(request.form['amount'])
        )
        db.session.add(entry)
        db.session.commit()
        flash("expense saved","success")
        return redirect(url_for('dashboard'))

    return render_template(
        'add_income.html',
        valid_accounts=valid_accounts,
        role=role,
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
            except ValueError:
                pass
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated","success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)

# ─── FINANCE REPORT & EXPORT ─────────────────────────────────────────────────

@app.route('/report')
def report():
    # grab any filters from query-string
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    # load everything from the one unified file
    entries = load_json(ENTRIES_FILE, default=list)

    # apply filter logic
    def include(e):
        if dept_f and e['department'] != dept_f:
            return False
        if frm   and e['date'] < frm:
            return False
        if to    and e['date'] > to:
            return False
        return True

    rows = [e for e in entries if include(e)]
    rows.sort(key=lambda e: e['date'], reverse=True)

    return render_template(
      'report.html',
      data=rows,
      department_filter=dept_f,
      from_date=frm,
      to_date=to
    )

# ─── EXPORT EXCEL ─────────────────────────────────────────────────────────
@app.route('/export-excel')
def export_excel():
    # 1) grab filters
    dept_f = request.args.get('department', '').lower()
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    # 2) load & filter
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and dept_f not in e['department'].lower():
            continue
        if frm and e['date'] < frm:
            continue
        if to and e['date'] > to:
            continue

        rows.append({
            'Date':        e['date'],
            'Department':  e['department'],
            'Type':        e['type'],
            'Subtype':     e.get('subtype',''),
            'Description': e.get('description',''),
            'Amount (R)':  e['amount']
        })

    # 3) build DataFrame & Excel
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    output.seek(0)

    # 4) send
    filename = f"report_{dept_f or 'all'}_{frm}_{to}.xlsx"
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ─── EXPORT PDF ───────────────────────────────────────────────────────────
@app.route('/export-pdf')
def export_pdf():
    # same filters
    dept_f = request.args.get('department', '').lower()
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    # load & filter
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and dept_f not in e['department'].lower():
            continue
        if frm and e['date'] < frm:
            continue
        if to and e['date'] > to:
            continue

        rows.append({
            'date':        e['date'],
            'department':  e['department'],
            'type':        e['type'],
            'subtype':     e.get('subtype',''),
            'description': e.get('description',''),
            'amount':      e['amount']
        })

    rows.sort(key=lambda x: x['date'], reverse=True)

    # render your PDF-friendly template
    return render_template(
        'report_pdf.html',
        data=rows,
        now=datetime.now()
    )

# ─── RUN SERVER ────────────────────────────────────────────────────────────
if __name__=='__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT',10000)),
        debug=True
    )
